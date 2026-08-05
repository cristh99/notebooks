"""Extract labeled development crops from the selected CORD detector-v4 rule.

CORD is already opened development data. Full-image candidate construction is
strictly outcome-blind; expert truth and geometry are used only to identify and
label the preselected risk unit after detector execution. The extracted crops
feed later train/holdout experiments and can never certify the detector itself.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from PIL import Image

from .cord_consensus_detector_v4 import (
    STATUS as DEVELOPMENT_STATUS,
    cluster_candidates,
    crop_guard_readings,
    guard_accepts,
    resolved_tokens,
    tesseract_numeric_candidates,
)
from .cord_natural_holdout import (
    SHARD_SPECS,
    crop_box,
    image_bytes_from_row,
    iter_parquet_rows,
    parse_ground_truth,
    receipt_identity,
    select_numeric_annotation,
    sha256_path,
    verify_hash_manifest,
)
from .core import canonical_json, p95, sha256_bytes, sha256_file
from .sroie_natural_holdout import (
    eligibility,
    match_ocr_claim,
    stable_payload,
    verify_stable_payload,
)

SHARD_SCHEMA = "ocr-cord-detector-v4-crops-shard/1"
INDEX_SCHEMA = "ocr-cord-detector-v4-crops-index/1"
SELECTED_CONFIGURATION: dict[str, Any] = {
    "id": "broad-v2-conflict-ok-psm7_any",
    "psm_set": "broad",
    "psms": [3, 4, 6, 11, 12],
    "minimum_distinct_psm_votes": 2,
    "reject_equal_length_conflict": False,
    "guard_mode": "psm7_any",
    "uses_truth_for_candidate_construction": False,
    "uses_annotation_bbox_for_candidate_construction": False,
}
DETECTOR_DEVELOPMENT_STABLE_PAYLOAD_SHA256 = (
    "cdad9018a3049848ad86fc53ce9a4a201391b8d36c2106d8239160226692b58b"
)


def _write_hash_manifest(root: Path) -> None:
    lines = [
        f"{sha256_path(path)}  {path.relative_to(root)}"
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (root / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _verify_manifest_identity(manifest: Mapping[str, Any]) -> None:
    if not verify_stable_payload(manifest, "manifest_sha256"):
        raise RuntimeError("CORD manifest stable payload failed")
    shard_id = str(manifest.get("dataset", {}).get("shard_id") or "")
    if shard_id not in SHARD_SPECS:
        raise RuntimeError(f"unexpected CORD shard: {shard_id}")
    spec = SHARD_SPECS[shard_id]
    if manifest["dataset"]["split"] != spec["split"]:
        raise RuntimeError("CORD manifest split identity changed")
    if manifest["dataset"]["filename"] != spec["filename"]:
        raise RuntimeError("CORD manifest filename identity changed")


def extract_shard(
    parquet_path: Path,
    manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_manifest_identity(manifest)
    if sha256_path(parquet_path) != manifest["dataset"]["parquet_sha256"]:
        raise RuntimeError("CORD parquet changed after protocol sealing")
    records = {
        int(record["row_index"]): dict(record)
        for record in manifest["records"]
    }
    if len(records) != len(manifest["records"]):
        raise RuntimeError("duplicate selected row index")
    shard_id = str(manifest["dataset"]["shard_id"])
    split = str(manifest["dataset"]["split"])
    shutil.rmtree(output_dir, ignore_errors=True)
    crops_dir = output_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    processed: set[int] = set()
    extracted: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    psm_seconds: Counter[int] = Counter()
    psm_timeouts: Counter[int] = Counter()
    raw_candidate_counts: Counter[int] = Counter()
    guard_seconds: list[float] = []

    for row_index, row in iter_parquet_rows(parquet_path):
        record = records.get(row_index)
        if record is None:
            continue
        processed.add(row_index)
        payload = parse_ground_truth(row.get("ground_truth"))
        key, image_id = receipt_identity(payload, split)
        if key != record["key"] or image_id != int(record["image_id"]):
            raise RuntimeError("CORD receipt identity changed")
        image_bytes = image_bytes_from_row(row)
        image_sha = sha256_bytes(image_bytes)
        if image_sha != record["image_sha256"]:
            raise RuntimeError("CORD image changed")
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGB")
        selected, _ = select_numeric_annotation(
            payload=payload,
            shard_id=shard_id,
            split=split,
            key=key,
            image_sha256=image_sha,
            image_size=image.size,
        )
        if selected is None or any(
            selected[field] != record[field]
            for field in ("truth", "bbox", "selection_rank_sha256")
        ):
            raise RuntimeError("CORD numeric selection changed")

        raw_candidates: list[dict[str, Any]] = []
        for psm in SELECTED_CONFIGURATION["psms"]:
            candidates, runtime = tesseract_numeric_candidates(image, int(psm))
            raw_candidates.extend(candidates)
            psm_seconds[int(psm)] += float(runtime["wall_seconds"])
            psm_timeouts[int(psm)] += int(bool(runtime["timeout"]))
            raw_candidate_counts[int(psm)] += int(runtime["numeric_candidates"])
        clusters = cluster_candidates(raw_candidates)
        tokens = resolved_tokens(clusters, SELECTED_CONFIGURATION)
        matched = match_ocr_claim(record["bbox"], tokens)
        claim, eligible, reason = eligibility(str(record["truth"]), matched)
        reasons[reason] += 1
        if not eligible:
            print(
                json.dumps(
                    {
                        "shard_id": shard_id,
                        "processed": len(processed),
                        "selected": len(records),
                        "extracted": len(extracted),
                        "reason": reason,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            continue

        detector_box = crop_box(image, matched["bbox"], margin=2)
        crop = image.crop(detector_box)
        evidence_key = sha256_bytes(
            canonical_json(
                {
                    "image_sha256": image_sha,
                    "truth_bbox": record["bbox"],
                    "detector_bbox": matched["bbox"],
                    "detector_configuration": SELECTED_CONFIGURATION["id"],
                }
            ).encode("utf-8")
        )
        crop_path = crops_dir / f"{evidence_key}.png"
        crop.save(crop_path, optimize=False)
        guard = crop_guard_readings(crop)
        guard_seconds.append(float(guard["wall_seconds"]))
        extracted.append(
            {
                "schema": "ocr-cord-detector-v4-crop/1",
                "dataset": "CORD-v2",
                "shard_id": shard_id,
                "split": split,
                "row_index": row_index,
                "key": key,
                "image_id": image_id,
                "image_sha256": image_sha,
                "merchant_group": str(record["merchant_group"]),
                "evidence_key": evidence_key,
                "truth": str(record["truth"]),
                "claim": claim,
                "claim_correct": claim == str(record["truth"]),
                "counterfactual_claim": str(record["counterfactual_claim"]),
                "truth_bbox": list(record["bbox"]),
                "detector_bbox": list(matched["bbox"]),
                "detector_crop_box": list(detector_box),
                "detector_match": matched,
                "detector_configuration": dict(SELECTED_CONFIGURATION),
                "crop_file": f"crops/{crop_path.name}",
                "crop_sha256": sha256_file(crop_path),
                "guard": guard,
                "guard_accepts_claim": guard_accepts(
                    guard, claim, "psm7_any"
                ),
                "guard_accepts_counterfactual": guard_accepts(
                    guard, str(record["counterfactual_claim"]), "psm7_any"
                ),
            }
        )
        print(
            json.dumps(
                {
                    "shard_id": shard_id,
                    "processed": len(processed),
                    "selected": len(records),
                    "extracted": len(extracted),
                    "claim_correct": claim == str(record["truth"]),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    if processed != set(records):
        raise RuntimeError(
            f"selected CORD rows missing: {sorted(set(records) - processed)[:10]}"
        )
    extracted.sort(key=lambda row: (int(row["row_index"]), str(row["key"])))
    report: dict[str, Any] = {
        "schema": SHARD_SCHEMA,
        "status": DEVELOPMENT_STATUS,
        "dataset": dict(manifest["dataset"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "detector_development_stable_payload_sha256": (
            DETECTOR_DEVELOPMENT_STABLE_PAYLOAD_SHA256
        ),
        "selected_configuration": dict(SELECTED_CONFIGURATION),
        "execution": {
            "selected_locations": len(records),
            "detector_eligible_crops": len(extracted),
            "correct_claim_crops": sum(
                bool(record["claim_correct"]) for record in extracted
            ),
            "natural_error_crops": sum(
                not bool(record["claim_correct"]) for record in extracted
            ),
            "guard_accepts_claim": sum(
                bool(record["guard_accepts_claim"]) for record in extracted
            ),
            "guard_accepts_counterfactual": sum(
                bool(record["guard_accepts_counterfactual"])
                for record in extracted
            ),
            "reasons": dict(sorted(reasons.items())),
        },
        "runtime": {
            "psm_wall_seconds": {
                str(key): value for key, value in sorted(psm_seconds.items())
            },
            "psm_timeouts": {
                str(key): value for key, value in sorted(psm_timeouts.items())
            },
            "numeric_candidates": {
                str(key): value
                for key, value in sorted(raw_candidate_counts.items())
            },
            "median_guard_seconds": (
                statistics.median(guard_seconds) if guard_seconds else None
            ),
            "p95_guard_seconds": p95(guard_seconds),
        },
        "records": extracted,
        "decision": {
            "development_crops_complete": True,
            "external_certificate": False,
            "production_ready": False,
            "fresh_external_corpus_required": True,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    report = stable_payload(report, "stable_payload_sha256")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "cord_detector_crops_v4_shard.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_hash_manifest(output_dir)
    return report


def aggregate_shards(
    roots: Iterable[Path], output_dir: Path
) -> dict[str, Any]:
    reports: dict[str, dict[str, Any]] = {}
    combined_records: list[dict[str, Any]] = []
    for root in sorted(roots):
        verify_hash_manifest(root)
        report = json.loads(
            (root / "cord_detector_crops_v4_shard.json").read_text(
                encoding="utf-8"
            )
        )
        if report.get("schema") != SHARD_SCHEMA:
            raise RuntimeError(f"unexpected crop shard schema: {root}")
        if not verify_stable_payload(report, "stable_payload_sha256"):
            raise RuntimeError(f"crop shard stable payload failed: {root}")
        shard_id = str(report["dataset"]["shard_id"])
        if shard_id in reports:
            raise RuntimeError(f"duplicate crop shard: {shard_id}")
        if report["selected_configuration"] != SELECTED_CONFIGURATION:
            raise RuntimeError("crop shard detector configuration changed")
        for record in report["records"]:
            crop_path = root / str(record["crop_file"])
            if sha256_file(crop_path) != record["crop_sha256"]:
                raise RuntimeError(f"crop hash mismatch: {crop_path}")
            combined_records.append(
                {
                    "shard_id": shard_id,
                    "split": record["split"],
                    "key": record["key"],
                    "evidence_key": record["evidence_key"],
                    "claim": record["claim"],
                    "truth": record["truth"],
                    "claim_correct": record["claim_correct"],
                    "counterfactual_claim": record["counterfactual_claim"],
                    "crop_sha256": record["crop_sha256"],
                    "root_name": root.name,
                    "crop_file": record["crop_file"],
                }
            )
        reports[shard_id] = report
    if set(reports) != set(SHARD_SPECS):
        raise RuntimeError(
            f"crop aggregate requires six shards: {sorted(reports)}"
        )
    if len({(row["shard_id"], row["key"]) for row in combined_records}) != len(
        combined_records
    ):
        raise RuntimeError("duplicate CORD crop record association")
    split_counts = Counter(str(row["split"]) for row in combined_records)
    result: dict[str, Any] = {
        "schema": INDEX_SCHEMA,
        "status": DEVELOPMENT_STATUS,
        "detector_development_stable_payload_sha256": (
            DETECTOR_DEVELOPMENT_STABLE_PAYLOAD_SHA256
        ),
        "selected_configuration": dict(SELECTED_CONFIGURATION),
        "execution": {
            "shards": len(reports),
            "detector_eligible_crops": len(combined_records),
            "crops_by_split": dict(sorted(split_counts.items())),
            "correct_claim_crops": sum(
                bool(row["claim_correct"]) for row in combined_records
            ),
            "natural_error_crops": sum(
                not bool(row["claim_correct"]) for row in combined_records
            ),
            "unique_crop_sha256": len(
                {str(row["crop_sha256"]) for row in combined_records}
            ),
            "record_set_sha256": sha256_bytes(
                canonical_json(combined_records).encode("utf-8")
            ),
        },
        "shards": {
            shard_id: {
                "stable_payload_sha256": report["stable_payload_sha256"],
                "selected_locations": report["execution"]["selected_locations"],
                "detector_eligible_crops": report["execution"][
                    "detector_eligible_crops"
                ],
                "natural_error_crops": report["execution"][
                    "natural_error_crops"
                ],
            }
            for shard_id, report in sorted(reports.items())
        },
        "records": sorted(
            combined_records,
            key=lambda row: (
                str(row["split"]),
                str(row["shard_id"]),
                str(row["key"]),
            ),
        ),
        "decision": {
            "ready_for_train_holdout_separation": True,
            "external_certificate": False,
            "production_ready": False,
            "fresh_external_corpus_required": True,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    result = stable_payload(result, "stable_payload_sha256")
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "cord_detector_crops_v4_index.json"
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_hash_manifest(output_dir)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--parquet", required=True, type=Path)
    extract.add_argument("--manifest", required=True, type=Path)
    extract.add_argument("--output-dir", required=True, type=Path)
    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("roots", nargs="+", type=Path)
    aggregate.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "extract":
        report = extract_shard(args.parquet, args.manifest, args.output_dir)
        print(
            json.dumps(
                {
                    "dataset": report["dataset"],
                    "execution": report["execution"],
                    "runtime": report["runtime"],
                    "stable_payload_sha256": report[
                        "stable_payload_sha256"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = aggregate_shards(args.roots, args.output_dir)
    print(
        json.dumps(
            {
                "execution": result["execution"],
                "decision": result["decision"],
                "stable_payload_sha256": result[
                    "stable_payload_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
