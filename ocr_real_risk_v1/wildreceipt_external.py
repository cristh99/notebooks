"""Sealed external validation of numeric-consensus-v4 on WildReceipt.

The model, thresholds, risk unit, corrected LayoutLM coordinate projection,
evaluator, and exact gates are frozen before any OCR outcome is generated. A
prior manifest-only attempt exposed the normalized bbox schema; it installed
no OCR binary and executed neither OCR nor candidate inference. Exactly one
selected numeric annotation may survive per unique decoded receipt image.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image

from .cord_consensus_detector_v4 import (
    cluster_candidates,
    crop_guard_readings,
    guard_accepts,
    resolved_tokens,
    tesseract_numeric_candidates,
)
from .core import canonical_json, mutate_one_digit, p95, sha256_bytes, sha256_file
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .numeric_consensus_candidate_v4_wildreceipt import (
    CANDIDATE_ID,
    SOURCE_OBJECTS,
    external_protocol,
    verify_manifest as verify_candidate_manifest,
)
from .numeric_digit_forest import infer_claim
from .numeric_digit_forest_deterministic import load_frozen_candidate
from .sroie_natural_holdout import (
    eligibility,
    match_ocr_claim,
    stable_payload,
    tesseract_tokens,
    verify_stable_payload,
)
from .wildreceipt_adapter import (
    DATASET_ID,
    DATASET_REVISION,
    iter_parquet_rows,
    physical_evidence_key,
    receipt_key,
    row_image,
    select_numeric_annotation,
)

MANIFEST_SCHEMA = "ocr-wildreceipt-numeric-manifest/1"
PROTOCOL_SCHEMA = "ocr-wildreceipt-numeric-protocol/1"
REPORT_SCHEMA = "ocr-wildreceipt-numeric-shard/1"
AGGREGATE_SCHEMA = "ocr-wildreceipt-numeric-aggregate/1"
FAMILY_ALPHA = 0.05
ALPHA_PER_LEG = FAMILY_ALPHA / 4.0
TARGET_REDUCTION = 10.0
MINIMUM_SELECTED = 1200
MINIMUM_ACCEPTED = 400
MINIMUM_COVERAGE = 0.25
COUNTERFACTUAL_MAXIMUM_UPPER = 0.01
MINIMUM_STABILITY_PASS_FRACTION = 2.0 / 3.0
DEVELOPMENT_ACCEPTANCE_RATE = 319 / 993

SHARDS = {
    spec["shard_id"]: {
        "path": path,
        **spec,
    }
    for path, spec in SOURCE_OBJECTS.items()
}


def sha256_path(path: Path) -> str:
    return sha256_file(path)


def write_hash_manifest(root: Path) -> None:
    lines = [
        f"{sha256_path(path)}  {path.relative_to(root)}"
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (root / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def verify_hash_manifest(root: Path) -> None:
    path = root / "SHA256SUMS.txt"
    if not path.is_file():
        raise RuntimeError(f"missing SHA256SUMS.txt in {root}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        expected, relative = raw.split("  ", 1)
        target = root / relative
        if sha256_path(target) != expected:
            raise RuntimeError(f"hash mismatch: {target}")


def load_candidate_bundle(root: Path) -> tuple[dict[str, Any], Any]:
    manifest_path = root / "frozen_candidate.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("unexpected WildReceipt candidate id")
    if not verify_candidate_manifest(manifest):
        raise RuntimeError("WildReceipt candidate stable payload failed")
    if manifest.get("status") != (
        "FROZEN_AFTER_WILDRECEIPT_GEOMETRY_SCHEMA_DISCOVERY_"
        "BEFORE_ANY_OCR_OUTCOMES"
    ):
        raise RuntimeError("WildReceipt candidate has an unexpected status")
    if manifest.get("external_protocol") != external_protocol():
        raise RuntimeError("WildReceipt external protocol changed")
    source_binding = manifest.get("external_source_binding", {})
    if source_binding.get("source_rows_opened_before_this_freeze") is not True:
        raise RuntimeError("WildReceipt schema discovery is not disclosed")
    if source_binding.get("ocr_executed_before_this_freeze") is not False:
        raise RuntimeError("WildReceipt OCR outcomes were opened before freeze")
    if source_binding.get(
        "candidate_inference_executed_before_this_freeze"
    ) is not False:
        raise RuntimeError("candidate inference ran before repaired freeze")
    decision = manifest.get("decision", {})
    if decision.get(
        "candidate_frozen_before_wildreceipt_ocr_outcomes"
    ) is not True:
        raise RuntimeError("candidate was not frozen before OCR outcomes")
    if decision.get(
        "candidate_frozen_before_wildreceipt_source_opening"
    ) is not False:
        raise RuntimeError("source-opening chronology is misstated")
    if decision.get("untouched_external_certificate_claimed") is not False:
        raise RuntimeError("candidate improperly claims an untouched corpus")
    if manifest.get("decision", {}).get("production_ready") is not False:
        raise RuntimeError("WildReceipt candidate improperly claims production readiness")
    model_candidate, model = load_frozen_candidate(root / "model")
    expected_model_sha = manifest["digit_model"]["model_sha256"]
    if model_candidate.get("model", {}).get("sha256") != expected_model_sha:
        raise RuntimeError("candidate manifest/model artifact mismatch")
    if float(manifest["digit_model"]["threshold"]) != 0.25:
        raise RuntimeError("WildReceipt candidate threshold changed")
    if len(model.estimators_) != 500:
        raise RuntimeError("WildReceipt candidate tree count changed")
    return manifest, model


def _source_spec(shard_id: str) -> dict[str, Any]:
    try:
        return dict(SHARDS[shard_id])
    except KeyError as exc:
        raise ValueError(f"unknown WildReceipt shard: {shard_id}") from exc


def build_shard_manifest(
    parquet_path: Path,
    shard_id: str,
    candidate_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    spec = _source_spec(shard_id)
    observed_sha = sha256_path(parquet_path)
    observed_size = parquet_path.stat().st_size
    if observed_sha != spec["sha256"]:
        raise RuntimeError(f"WildReceipt source SHA-256 mismatch for {shard_id}")
    if observed_size != int(spec["size_bytes"]):
        raise RuntimeError(f"WildReceipt source size mismatch for {shard_id}")
    candidate_stable = str(candidate_manifest.get("stable_payload_sha256") or "")
    if len(candidate_stable) != 64:
        raise RuntimeError("candidate stable payload is missing")

    census: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    keys: set[str] = set()
    image_counts: Counter[str] = Counter()
    truth_lengths: Counter[int] = Counter()
    for row_index, row in iter_parquet_rows(parquet_path):
        census["rows"] += 1
        key = receipt_key(row, shard_id)
        if key in keys:
            raise RuntimeError(f"duplicate WildReceipt key within shard: {key}")
        keys.add(key)
        image_bytes, image, image_sha = row_image(row)
        image_counts[image_sha] += 1
        selected, counts = select_numeric_annotation(
            row=row,
            shard_id=shard_id,
            image_sha256=image_sha,
            image_size=image.size,
        )
        census.update(counts)
        if selected is None:
            census["rows_without_numeric_candidate"] += 1
            continue
        evidence_key = physical_evidence_key(image_sha, selected["bbox"])
        counterfactual = mutate_one_digit(
            str(selected["truth"]),
            (
                f"{DATASET_REVISION}:{shard_id}:{key}:"
                f"{selected['selection_rank_sha256']}"
            ),
        )
        records.append(
            {
                "shard_id": shard_id,
                "split": spec["split"],
                "row_index": row_index,
                "key": key,
                "receipt_id": str(row["id"]),
                "image_sha256": image_sha,
                "image_width": image.width,
                "image_height": image.height,
                "evidence_key": evidence_key,
                **selected,
                "counterfactual_claim": counterfactual,
                "active_physical_unit": True,
            }
        )
        truth_lengths[len(str(selected["truth"]))] += 1
        census["rows_with_selected_numeric_location"] += 1
        del image_bytes, image
    records.sort(key=lambda row: (int(row["row_index"]), str(row["key"])))
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "dataset": {
            "repo": DATASET_ID,
            "revision": DATASET_REVISION,
            "shard_id": shard_id,
            "split": spec["split"],
            "path": spec["path"],
            "parquet_sha256": observed_sha,
            "size_bytes": observed_size,
            "rows": census["rows"],
        },
        "candidate_binding": {
            "candidate_id": candidate_manifest["candidate_id"],
            "candidate_stable_payload_sha256": candidate_stable,
            "source_commit": candidate_manifest["source_commit"],
            "model_sha256": candidate_manifest["digit_model"]["model_sha256"],
            "threshold": candidate_manifest["digit_model"]["threshold"],
        },
        "protocol": dict(candidate_manifest["external_protocol"]),
        "census": {
            **dict(sorted(census.items())),
            "unique_keys": len(keys),
            "unique_images": len(image_counts),
            "duplicate_image_associations": sum(
                count - 1 for count in image_counts.values() if count > 1
            ),
            "truth_length_distribution": {
                str(key): value for key, value in sorted(truth_lengths.items())
            },
            "selected_key_set_sha256": sha256_bytes(
                canonical_json([row["key"] for row in records]).encode("utf-8")
            ),
        },
        "records": records,
    }
    return stable_payload(manifest, "manifest_sha256")


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise RuntimeError(f"unexpected WildReceipt manifest schema: {path}")
    if not verify_stable_payload(manifest, "manifest_sha256"):
        raise RuntimeError(f"WildReceipt manifest stable payload failed: {path}")
    return manifest


def build_protocol_bundle(
    manifest_paths: Sequence[Path],
    candidate_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    candidate_manifest, _ = load_candidate_bundle(candidate_root)
    manifests: dict[str, dict[str, Any]] = {}
    for path in manifest_paths:
        manifest = _load_manifest(path)
        shard_id = str(manifest["dataset"]["shard_id"])
        if shard_id in manifests:
            raise RuntimeError(f"duplicate WildReceipt manifest: {shard_id}")
        manifests[shard_id] = manifest
    if set(manifests) != set(SHARDS):
        raise RuntimeError(
            f"protocol requires exact WildReceipt shards: {sorted(manifests)}"
        )
    expected_binding = {
        "candidate_id": candidate_manifest["candidate_id"],
        "candidate_stable_payload_sha256": candidate_manifest[
            "stable_payload_sha256"
        ],
        "source_commit": candidate_manifest["source_commit"],
        "model_sha256": candidate_manifest["digit_model"]["model_sha256"],
        "threshold": candidate_manifest["digit_model"]["threshold"],
    }
    all_records = []
    for shard_id, manifest in manifests.items():
        if manifest["candidate_binding"] != expected_binding:
            raise RuntimeError(f"manifest binds a different candidate: {shard_id}")
        if manifest["protocol"] != candidate_manifest["external_protocol"]:
            raise RuntimeError(f"manifest protocol changed: {shard_id}")
        spec = SHARDS[shard_id]
        for field, expected in {
            "path": spec["path"],
            "parquet_sha256": spec["sha256"],
            "size_bytes": spec["size_bytes"],
            "split": spec["split"],
        }.items():
            if manifest["dataset"][field] != expected:
                raise RuntimeError(f"manifest source identity changed: {shard_id}.{field}")
        all_records.extend(manifest["records"])

    by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in all_records:
        by_image[str(record["image_sha256"])].append(record)
    duplicate_groups: list[dict[str, Any]] = []
    for image_sha, rows in sorted(by_image.items()):
        rows.sort(key=lambda row: (str(row["shard_id"]), str(row["key"])))
        representative = rows[0]
        for row in rows[1:]:
            if (
                row["truth"] != representative["truth"]
                or row["bbox"] != representative["bbox"]
                or row["counterfactual_claim"]
                != representative["counterfactual_claim"]
            ):
                raise RuntimeError(
                    f"duplicate WildReceipt image has conflicting selected risk unit: {image_sha}"
                )
        for index, row in enumerate(rows):
            row["active_physical_unit"] = index == 0
            row["canonical_owner_key"] = representative["key"]
        if len(rows) > 1:
            duplicate_groups.append(
                {
                    "image_sha256": image_sha,
                    "association_count": len(rows),
                    "keys": [row["key"] for row in rows],
                    "canonical_owner_key": representative["key"],
                }
            )
    active_records = [
        record for record in all_records if bool(record["active_physical_unit"])
    ]
    selected_count = len(active_records)
    projected_accepted = selected_count * DEVELOPMENT_ACCEPTANCE_RATE
    run_ocr = bool(
        selected_count >= MINIMUM_SELECTED
        and projected_accepted >= MINIMUM_ACCEPTED
    )
    for manifest in manifests.values():
        manifest.pop("manifest_sha256", None)
        manifest["manifest_sha256"] = sha256_bytes(
            canonical_json(manifest).encode("utf-8")
        )
    protocol: dict[str, Any] = {
        "schema": PROTOCOL_SCHEMA,
        "status": (
            "SEALED_AFTER_GEOMETRY_SCHEMA_REPAIR_BEFORE_WILDRECEIPT_OCR"
        ),
        "dataset": {
            "repo": DATASET_ID,
            "revision": DATASET_REVISION,
            "source_objects": dict(SOURCE_OBJECTS),
        },
        "candidate_binding": expected_binding,
        "candidate_protocol": dict(candidate_manifest["external_protocol"]),
        "census": {
            "published_rows": sum(
                int(manifest["dataset"]["rows"])
                for manifest in manifests.values()
            ),
            "receipt_associated_selected_locations": len(all_records),
            "unique_physical_selected_receipts": selected_count,
            "duplicate_image_associations": len(all_records) - selected_count,
            "duplicate_image_groups": duplicate_groups,
            "active_unit_set_sha256": sha256_bytes(
                canonical_json(
                    sorted(
                        [
                            {
                                "key": row["key"],
                                "image_sha256": row["image_sha256"],
                                "bbox": row["bbox"],
                                "truth": row["truth"],
                            }
                            for row in active_records
                        ],
                        key=lambda row: (row["image_sha256"], row["key"]),
                    )
                ).encode("utf-8")
            ),
        },
        "power_gate": {
            "minimum_selected_unique_receipts": MINIMUM_SELECTED,
            "minimum_accepted": MINIMUM_ACCEPTED,
            "selected_available": selected_count,
            "selected_pass": selected_count >= MINIMUM_SELECTED,
            "development_acceptance_rate": DEVELOPMENT_ACCEPTANCE_RATE,
            "projected_accepted": projected_accepted,
            "projected_accepted_pass": projected_accepted >= MINIMUM_ACCEPTED,
            "run_ocr": run_ocr,
        },
        "execution_plan": {
            "candidate_bytes_fixed_before_ocr": True,
            "selection_completed_before_ocr": True,
            "geometry_schema_repair_disclosed": True,
            "untouched_external_certificate": False,
            "three_source_shards": True,
            "one_worker_per_source_shard": True,
            "aggregate_recomputes_exact_bounds": True,
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
    protocol = stable_payload(protocol, "stable_payload_sha256")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir = output_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    for shard_id, manifest in sorted(manifests.items()):
        (manifests_dir / f"{shard_id}.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (output_dir / "protocol.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_hash_manifest(output_dir)
    return protocol


def evaluate_shard(
    parquet_path: Path,
    manifest_path: Path,
    candidate_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    shard_id = str(manifest["dataset"]["shard_id"])
    spec = _source_spec(shard_id)
    if sha256_path(parquet_path) != spec["sha256"]:
        raise RuntimeError("WildReceipt parquet changed after protocol sealing")
    candidate_manifest, model = load_candidate_bundle(candidate_root)
    if manifest["candidate_binding"]["candidate_stable_payload_sha256"] != (
        candidate_manifest["stable_payload_sha256"]
    ):
        raise RuntimeError("evaluation manifest binds a different candidate")
    records = {
        int(record["row_index"]): dict(record)
        for record in manifest["records"]
        if bool(record.get("active_physical_unit"))
    }
    observations: list[dict[str, Any]] = []
    processed: set[int] = set()
    baseline_reasons: Counter[str] = Counter()
    candidate_reasons: Counter[str] = Counter()
    psm_seconds: Counter[int] = Counter()
    psm_timeouts: Counter[int] = Counter()
    baseline_seconds: list[float] = []
    forest_seconds: list[float] = []
    guard_seconds: list[float] = []
    for row_index, row in iter_parquet_rows(parquet_path):
        record = records.get(row_index)
        if record is None:
            continue
        processed.add(row_index)
        key = receipt_key(row, shard_id)
        if key != record["key"]:
            raise RuntimeError("WildReceipt receipt key changed after sealing")
        _, image, image_sha = row_image(row)
        if image_sha != record["image_sha256"]:
            raise RuntimeError("WildReceipt image changed after sealing")
        selected, _ = select_numeric_annotation(
            row=row,
            shard_id=shard_id,
            image_sha256=image_sha,
            image_size=image.size,
        )
        if selected is None or any(
            selected[field] != record[field]
            for field in ("truth", "bbox", "selection_rank_sha256")
        ):
            raise RuntimeError("WildReceipt selected annotation changed after sealing")
        truth = str(record["truth"])
        counterfactual = str(record["counterfactual_claim"])

        baseline_tokens, baseline_runtime = tesseract_tokens(image)
        baseline_seconds.append(float(baseline_runtime["wall_seconds"]))
        baseline_matched = match_ocr_claim(record["bbox"], baseline_tokens)
        baseline_claim, baseline_eligible, baseline_reason = eligibility(
            truth, baseline_matched
        )
        baseline_reasons[baseline_reason] += 1

        raw_candidates: list[dict[str, Any]] = []
        for psm in candidate_manifest["detector"]["configuration"]["psms"]:
            candidates, runtime = tesseract_numeric_candidates(image, int(psm))
            raw_candidates.extend(candidates)
            psm_seconds[int(psm)] += float(runtime["wall_seconds"])
            psm_timeouts[int(psm)] += int(bool(runtime["timeout"]))
        clusters = cluster_candidates(raw_candidates)
        resolved = resolved_tokens(
            clusters,
            candidate_manifest["detector"]["configuration"],
        )
        candidate_matched = match_ocr_claim(record["bbox"], resolved)
        candidate_claim, candidate_eligible, candidate_reason = eligibility(
            truth, candidate_matched
        )
        candidate_reasons[candidate_reason] += 1
        prediction = ""
        minimum_probability: float | None = None
        forest_accepted = False
        final_accepted = False
        counterfactual_false_accept = False
        guard: dict[str, Any] | None = None
        crop_coordinates: list[int] | None = None
        crop_sha256: str | None = None
        if candidate_eligible:
            from .sroie_natural_holdout import crop_box

            box = crop_box(image, candidate_matched["bbox"], margin=2)
            crop_coordinates = list(box)
            crop = image.crop(box)
            buffer = io.BytesIO()
            crop.save(buffer, format="PNG", optimize=False)
            crop_sha256 = sha256_bytes(buffer.getvalue())
            started = time.perf_counter()
            decision = infer_claim(model, crop, candidate_claim, threshold=0.25)
            forest_elapsed = time.perf_counter() - started
            forest_seconds.append(forest_elapsed)
            prediction = str(decision.get("prediction") or "")
            minimum_probability = float(
                decision.get("minimum_mean_probability") or 0.0
            )
            forest_accepted = bool(decision.get("accepted"))
            guard = crop_guard_readings(crop)
            guard_seconds.append(float(guard["wall_seconds"]))
            final_accepted = bool(
                forest_accepted
                and guard_accepts(guard, candidate_claim, "psm7_any")
            )
            counterfactual_false_accept = bool(
                prediction == counterfactual
                and minimum_probability >= 0.25
                and guard_accepts(guard, counterfactual, "psm7_any")
            )
        observations.append(
            {
                "shard_id": shard_id,
                "split": spec["split"],
                "row_index": row_index,
                "key": key,
                "image_sha256": image_sha,
                "evidence_key": record["evidence_key"],
                "truth": truth,
                "bbox": record["bbox"],
                "counterfactual_claim": counterfactual,
                "baseline": {
                    "claim": baseline_claim,
                    "eligible": baseline_eligible,
                    "reason": baseline_reason,
                    "claim_correct": bool(
                        baseline_eligible and baseline_claim == truth
                    ),
                    "matched": baseline_matched,
                    "runtime": baseline_runtime,
                },
                "candidate": {
                    "claim": candidate_claim,
                    "eligible": candidate_eligible,
                    "reason": candidate_reason,
                    "claim_correct": bool(
                        candidate_eligible and candidate_claim == truth
                    ),
                    "matched": candidate_matched,
                    "prediction": prediction,
                    "minimum_mean_probability": minimum_probability,
                    "forest_accepted": forest_accepted,
                    "accepted": final_accepted,
                    "correct_accept": bool(
                        final_accepted and candidate_claim == truth
                    ),
                    "false_accept": bool(
                        final_accepted and candidate_claim != truth
                    ),
                    "crop_box": crop_coordinates,
                    "crop_sha256": crop_sha256,
                    "guard": guard,
                },
                "counterfactual": {
                    "claim": counterfactual,
                    "false_accept": counterfactual_false_accept,
                },
            }
        )
        print(
            json.dumps(
                {
                    "shard_id": shard_id,
                    "processed": len(observations),
                    "selected": len(records),
                    "baseline_errors": sum(
                        item["baseline"]["eligible"]
                        and not item["baseline"]["claim_correct"]
                        for item in observations
                    ),
                    "accepted": sum(
                        item["candidate"]["accepted"] for item in observations
                    ),
                    "false_accepted": sum(
                        item["candidate"]["false_accept"] for item in observations
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        del image
    if processed != set(records):
        raise RuntimeError(
            f"WildReceipt active rows not evaluated: {sorted(set(records) - processed)[:10]}"
        )
    observations.sort(key=lambda row: (int(row["row_index"]), str(row["key"])))
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "dataset": dict(manifest["dataset"]),
        "candidate_binding": dict(manifest["candidate_binding"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "execution": {
            "selected_unique_receipts": len(observations),
            "baseline_eligible": sum(
                row["baseline"]["eligible"] for row in observations
            ),
            "candidate_eligible": sum(
                row["candidate"]["eligible"] for row in observations
            ),
            "candidate_accepted": sum(
                row["candidate"]["accepted"] for row in observations
            ),
            "baseline_reasons": dict(sorted(baseline_reasons.items())),
            "candidate_reasons": dict(sorted(candidate_reasons.items())),
            "psm_timeouts": {
                str(key): value for key, value in sorted(psm_timeouts.items())
            },
        },
        "descriptive": {
            "baseline_errors": sum(
                row["baseline"]["eligible"]
                and not row["baseline"]["claim_correct"]
                for row in observations
            ),
            "candidate_false_accepts": sum(
                row["candidate"]["false_accept"] for row in observations
            ),
            "counterfactual_false_accepts": sum(
                row["counterfactual"]["false_accept"] for row in observations
            ),
            "median_baseline_seconds": (
                statistics.median(baseline_seconds) if baseline_seconds else None
            ),
            "p95_baseline_seconds": p95(baseline_seconds),
            "median_forest_ms": (
                statistics.median(forest_seconds) * 1000.0
                if forest_seconds
                else None
            ),
            "p95_forest_ms": (
                p95(forest_seconds) * 1000.0 if forest_seconds else None
            ),
            "median_guard_ms": (
                statistics.median(guard_seconds) * 1000.0
                if guard_seconds
                else None
            ),
            "p95_guard_ms": (
                p95(guard_seconds) * 1000.0 if guard_seconds else None
            ),
            "psm_wall_seconds": {
                str(key): value for key, value in sorted(psm_seconds.items())
            },
        },
        "observations": observations,
        "decision": {
            "shard_execution_complete": True,
            "aggregate_exact_certificate_required": True,
            "formal_10x_claimed_at_shard_level": False,
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
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "shard_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_hash_manifest(output_dir)
    return report


def exact_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    minimum_selected: int = MINIMUM_SELECTED,
    minimum_accepted: int = MINIMUM_ACCEPTED,
) -> dict[str, Any]:
    selected = list(rows)
    baseline_eligible = [row for row in selected if row["baseline"]["eligible"]]
    baseline_false = sum(
        not row["baseline"]["claim_correct"] for row in baseline_eligible
    )
    accepted = [row for row in selected if row["candidate"]["accepted"]]
    accepted_false = sum(row["candidate"]["false_accept"] for row in accepted)
    counter_false = sum(row["counterfactual"]["false_accept"] for row in selected)
    baseline_lower = (
        clopper_pearson_lower(
            baseline_false, len(baseline_eligible), ALPHA_PER_LEG
        )
        if baseline_eligible
        else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(
            accepted_false, len(accepted), ALPHA_PER_LEG
        )
        if accepted
        else 1.0
    )
    coverage_lower = (
        clopper_pearson_lower(len(accepted), len(selected), ALPHA_PER_LEG)
        if selected
        else 0.0
    )
    counter_upper = (
        clopper_pearson_upper(counter_false, len(selected), ALPHA_PER_LEG)
        if selected
        else 1.0
    )
    reduction_lower = (
        baseline_lower / candidate_upper if candidate_upper > 0 else None
    )
    passed = bool(
        len(selected) >= minimum_selected
        and baseline_false > 0
        and len(accepted) >= minimum_accepted
        and coverage_lower >= MINIMUM_COVERAGE
        and candidate_upper <= baseline_lower / TARGET_REDUCTION
        and counter_upper <= COUNTERFACTUAL_MAXIMUM_UPPER
    )
    return {
        "selected": len(selected),
        "baseline_eligible": len(baseline_eligible),
        "baseline_false": baseline_false,
        "accepted": len(accepted),
        "accepted_false": accepted_false,
        "counterfactual_false": counter_false,
        "baseline_lower": baseline_lower,
        "candidate_upper": candidate_upper,
        "coverage_lower": coverage_lower,
        "counterfactual_upper": counter_upper,
        "reduction_lower": reduction_lower,
        "minimum_selected_required": minimum_selected,
        "minimum_accepted_required": minimum_accepted,
        "pass": passed,
    }


def aggregate_reports(
    protocol_root: Path,
    shard_roots: Sequence[Path],
    output_dir: Path,
) -> dict[str, Any]:
    verify_hash_manifest(protocol_root)
    protocol = json.loads(
        (protocol_root / "protocol.json").read_text(encoding="utf-8")
    )
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise RuntimeError("unexpected WildReceipt protocol schema")
    if not verify_stable_payload(protocol, "stable_payload_sha256"):
        raise RuntimeError("WildReceipt protocol stable payload failed")
    if protocol.get("status") != (
        "SEALED_AFTER_GEOMETRY_SCHEMA_REPAIR_BEFORE_WILDRECEIPT_OCR"
    ):
        raise RuntimeError("WildReceipt repaired protocol was not sealed before OCR")
    reports: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for root in shard_roots:
        verify_hash_manifest(root)
        manifest = _load_manifest(root / "manifest.json")
        report = json.loads((root / "shard_report.json").read_text(encoding="utf-8"))
        if report.get("schema") != REPORT_SCHEMA:
            raise RuntimeError(f"unexpected WildReceipt report schema: {root}")
        if not verify_stable_payload(report, "stable_payload_sha256"):
            raise RuntimeError(f"WildReceipt report stable payload failed: {root}")
        shard_id = str(report["dataset"]["shard_id"])
        if shard_id in reports:
            raise RuntimeError(f"duplicate WildReceipt report: {shard_id}")
        sealed_manifest = _load_manifest(
            protocol_root / "manifests" / f"{shard_id}.json"
        )
        if canonical_json(manifest) != canonical_json(sealed_manifest):
            raise RuntimeError(f"evaluated manifest differs from sealed manifest: {shard_id}")
        if report["manifest_sha256"] != manifest["manifest_sha256"]:
            raise RuntimeError(f"report is not bound to manifest: {shard_id}")
        if report["candidate_binding"] != protocol["candidate_binding"]:
            raise RuntimeError(f"report binds another candidate: {shard_id}")
        reports[shard_id] = report
        observations.extend(report["observations"])
    if set(reports) != set(SHARDS):
        raise RuntimeError(f"aggregate requires three exact shards: {sorted(reports)}")
    image_hashes = [str(row["image_sha256"]) for row in observations]
    if len(set(image_hashes)) != len(image_hashes):
        raise RuntimeError("duplicate physical images survived protocol deduplication")
    if len(observations) != int(protocol["census"]["unique_physical_selected_receipts"]):
        raise RuntimeError("aggregate selected denominator differs from sealed protocol")
    overall = exact_summary(observations)
    folds = []
    shard_ids = sorted(reports)
    for held_out in shard_ids:
        subset = [row for row in observations if row["shard_id"] != held_out]
        fraction = len(subset) / max(len(observations), 1)
        fold = exact_summary(
            subset,
            minimum_selected=max(1, math.ceil(MINIMUM_SELECTED * fraction)),
            minimum_accepted=max(1, math.ceil(MINIMUM_ACCEPTED * fraction)),
        )
        folds.append({"held_out_shard": held_out, "summary": fold})
    stability_passes = sum(bool(fold["summary"]["pass"]) for fold in folds)
    stability_fraction = stability_passes / len(folds) if folds else 0.0
    stability_pass = bool(
        len(folds) == len(SHARDS)
        and stability_fraction >= MINIMUM_STABILITY_PASS_FRACTION
    )
    external_pass = bool(overall["pass"] and stability_pass)
    if external_pass:
        verdict = (
            "PASS_EXTERNAL_WILDRECEIPT_SCHEMA_REPAIRED_"
            "NUMERIC_10X_CERTIFICATE"
        )
    elif overall["selected"] < MINIMUM_SELECTED:
        verdict = "WILDRECEIPT_UNDERPOWERED_SELECTED_DENOMINATOR"
    elif overall["baseline_false"] == 0:
        verdict = "WILDRECEIPT_BASELINE_TOO_CLEAN_TO_CERTIFY"
    elif not overall["pass"]:
        verdict = "WILDRECEIPT_EXTERNAL_TENFOLD_BOUND_NOT_REACHED"
    else:
        verdict = "WILDRECEIPT_EXTERNAL_SHARD_STABILITY_FAILED"
    result: dict[str, Any] = {
        "schema": AGGREGATE_SCHEMA,
        "dataset": {
            "repo": DATASET_ID,
            "revision": DATASET_REVISION,
            "source_objects": dict(SOURCE_OBJECTS),
            "risk_unit": "one selected numeric annotation per unique physical receipt",
        },
        "candidate_binding": dict(protocol["candidate_binding"]),
        "protocol_binding": {
            "stable_payload_sha256": protocol["stable_payload_sha256"],
            "active_unit_set_sha256": protocol["census"][
                "active_unit_set_sha256"
            ],
        },
        "execution": {
            "published_rows": protocol["census"]["published_rows"],
            "selected_unique_receipts": len(observations),
            "duplicate_image_associations_removed": protocol["census"][
                "duplicate_image_associations"
            ],
            "source_shards": len(reports),
            "ocr_timeouts": sum(
                sum(int(value) for value in report["execution"]["psm_timeouts"].values())
                for report in reports.values()
            ),
        },
        "baseline": {
            "eligible_claims": overall["baseline_eligible"],
            "false_predictions": overall["baseline_false"],
            "observed_error_rate": (
                overall["baseline_false"] / overall["baseline_eligible"]
                if overall["baseline_eligible"]
                else None
            ),
            "simultaneous_95pct_lower": overall["baseline_lower"],
        },
        "candidate": {
            "accepted": overall["accepted"],
            "false_accepted": overall["accepted_false"],
            "observed_false_acceptance_rate": (
                overall["accepted_false"] / overall["accepted"]
                if overall["accepted"]
                else None
            ),
            "simultaneous_95pct_upper": overall["candidate_upper"],
            "coverage_observed": (
                overall["accepted"] / overall["selected"]
                if overall["selected"]
                else 0.0
            ),
            "simultaneous_95pct_coverage_lower": overall["coverage_lower"],
            "certified_error_reduction_lower": overall["reduction_lower"],
        },
        "counterfactual": {
            "cases": overall["selected"],
            "false_accepts": overall["counterfactual_false"],
            "simultaneous_95pct_upper": overall["counterfactual_upper"],
        },
        "stability": {
            "folds": len(folds),
            "passes": stability_passes,
            "pass_fraction": stability_fraction,
            "minimum_pass_fraction": MINIMUM_STABILITY_PASS_FRACTION,
            "pass": stability_pass,
            "details": folds,
        },
        "decision": {
            "schema_repaired_external_validation_complete": True,
            "candidate_bound_before_ocr_outcomes": True,
            "untouched_external_certificate_claimed": False,
            "pass_statistical_10x": external_pass,
            "tenfold_bound_reached": bool(overall["pass"]),
            "shard_stability_passed": stability_pass,
            "automatic_production_change": False,
            "honduras_production_readiness_claimed": False,
            "verdict": verdict,
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
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "wildreceipt_numeric_aggregate.json"
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_hash_manifest(output_dir)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    seal = subparsers.add_parser("seal")
    seal.add_argument("--parquet", required=True, type=Path)
    seal.add_argument("--shard-id", required=True, choices=tuple(SHARDS))
    seal.add_argument("--candidate-root", required=True, type=Path)
    seal.add_argument("--output", required=True, type=Path)

    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("manifests", nargs="+", type=Path)
    bundle.add_argument("--candidate-root", required=True, type=Path)
    bundle.add_argument("--output-dir", required=True, type=Path)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--parquet", required=True, type=Path)
    evaluate.add_argument("--manifest", required=True, type=Path)
    evaluate.add_argument("--candidate-root", required=True, type=Path)
    evaluate.add_argument("--output-dir", required=True, type=Path)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--protocol-root", required=True, type=Path)
    aggregate.add_argument("shard_roots", nargs="+", type=Path)
    aggregate.add_argument("--output-dir", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "seal":
        candidate, _ = load_candidate_bundle(args.candidate_root)
        manifest = build_shard_manifest(
            args.parquet, args.shard_id, candidate
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "dataset": manifest["dataset"],
                    "census": manifest["census"],
                    "manifest_sha256": manifest["manifest_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "bundle":
        result = build_protocol_bundle(
            args.manifests, args.candidate_root, args.output_dir
        )
    elif args.command == "evaluate":
        result = evaluate_shard(
            args.parquet,
            args.manifest,
            args.candidate_root,
            args.output_dir,
        )
    else:
        result = aggregate_reports(
            args.protocol_root, args.shard_roots, args.output_dir
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
