"""Frozen TextOCR external evaluation pipeline for numeric-consensus-v6.

The candidate and this complete pipeline are frozen before the TextOCR Parquet
footer, text, geometry, image, OCR output, or benchmark outcome is opened.
The cheap census reads metadata columns only. If it passes, this module verifies
the full 6.2 GB source, deduplicates physical images, creates twelve immutable
partitions, evaluates the candidate, injects one equal-length counterfactual
claim per risk unit, and computes exact aggregate and four-macrofold bounds.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import shutil
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow.parquet as pq
from PIL import Image

from .cord_consensus_detector_v4 import (
    cluster_candidates,
    crop_guard_readings,
    resolved_tokens,
    tesseract_numeric_candidates,
)
from .core import canonical_json, mutate_one_digit, p95, sha256_bytes, sha256_file
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .numeric_digit_forest import infer_claim
from .numeric_digit_forest_deterministic import load_frozen_candidate
from .sroie_natural_holdout import (
    crop_box,
    eligibility,
    image_bytes_from_row,
    match_ocr_claim,
    stable_payload,
    tesseract_tokens,
    verify_stable_payload,
)
from .textocr_adapter_v6 import (
    CENSUS_SCHEMA,
    DATASET_ID,
    DATASET_REVISION,
    SOURCE_PATH,
    SOURCE_SHA256,
    SOURCE_SIZE_BYTES,
)
from .wildreceipt_v6_gate_completion_lab import predict_v6_gate_completion

PREPARATION_SCHEMA = "ocr-textocr-prepared-protocol/6"
PARTITION_MANIFEST_SCHEMA = "ocr-textocr-partition-manifest/6"
PARTITION_REPORT_SCHEMA = "ocr-textocr-partition-report/6"
AGGREGATE_SCHEMA = "ocr-textocr-external-aggregate/6"
PARTITION_COUNT = 12
MACROFOLD_COUNT = 4
MINIMUM_STABILITY_PASS_FRACTION = 0.75
ALPHA_PER_LEG = 0.0125
TARGET_REDUCTION = 10.0
MINIMUM_SELECTED = 3000
MINIMUM_ACCEPTED = 900
MINIMUM_COVERAGE_LOWER = 0.25
COUNTERFACTUAL_MAXIMUM_UPPER = 0.01


def write_hash_manifest(root: Path) -> None:
    lines = [
        f"{sha256_file(path)}  {path.relative_to(root)}"
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
        if sha256_file(target) != expected:
            raise RuntimeError(f"hash mismatch: {target}")


def partition_id(record: Mapping[str, Any]) -> int:
    digest = sha256_bytes(
        canonical_json(
            {
                "dataset_revision": DATASET_REVISION,
                "row_index": int(record["row_index"]),
                "selection_rank_sha256": record[
                    "selection_rank_sha256"
                ],
                "truth": record["truth"],
                "bbox_xyxy": record["bbox_xyxy"],
            }
        ).encode("utf-8")
    )
    return int(digest[:16], 16) % PARTITION_COUNT


def macrofold_id(record: Mapping[str, Any]) -> int:
    return partition_id(record) % MACROFOLD_COUNT


def clip_bbox(
    bbox: Sequence[object], image: Image.Image
) -> tuple[int, int, int, int]:
    if len(bbox) != 4:
        raise RuntimeError("TextOCR selected bbox must contain four coordinates")
    try:
        x0, y0, x1, y1 = (float(value) for value in bbox)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("TextOCR selected bbox is non-numeric") from exc
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise RuntimeError("TextOCR selected bbox is non-finite")
    clipped = (
        max(0, min(image.width, int(math.floor(x0)))),
        max(0, min(image.height, int(math.floor(y0)))),
        max(0, min(image.width, int(math.ceil(x1)))),
        max(0, min(image.height, int(math.ceil(y1)))),
    )
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise RuntimeError("TextOCR selected bbox has no image overlap")
    return clipped


def _candidate_manifest(root: Path) -> dict[str, Any]:
    from .numeric_consensus_candidate_v6_textocr import verify_manifest

    payload = json.loads(
        (root / "frozen_candidate.json").read_text(encoding="utf-8")
    )
    if not verify_manifest(payload):
        raise RuntimeError("TextOCR v6 candidate stable payload failed")
    if payload.get("candidate_id") != "numeric-consensus-v6-textocr":
        raise RuntimeError("unexpected TextOCR candidate id")
    if payload.get("decision", {}).get(
        "candidate_frozen_before_textocr_opening"
    ) is not True:
        raise RuntimeError("TextOCR candidate was not frozen before opening")
    return payload


def load_candidate_bundle(root: Path) -> tuple[dict[str, Any], Any]:
    manifest = _candidate_manifest(root)
    model_candidate, model = load_frozen_candidate(root / "model")
    if model_candidate["model"]["sha256"] != manifest["digit_model"][
        "model_sha256"
    ]:
        raise RuntimeError("TextOCR candidate/model SHA-256 mismatch")
    if float(manifest["digit_model"]["threshold"]) != 0.25:
        raise RuntimeError("TextOCR digit threshold changed")
    if len(model.estimators_) != 500:
        raise RuntimeError("TextOCR tree count changed")
    return manifest, model


def _decode_image(raw: bytes, row_index: int) -> Image.Image:
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            image = opened.convert("RGB")
    except Exception as exc:
        raise RuntimeError(
            f"TextOCR image cannot be decoded at row {row_index}"
        ) from exc
    if image.width <= 0 or image.height <= 0:
        raise RuntimeError(f"TextOCR image dimensions invalid at row {row_index}")
    return image


def _load_census(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CENSUS_SCHEMA:
        raise RuntimeError("unexpected TextOCR census schema")
    if not verify_stable_payload(payload, "stable_payload_sha256"):
        raise RuntimeError("TextOCR census stable replay failed")
    if payload.get("dataset", {}).get("source_sha256") != SOURCE_SHA256:
        raise RuntimeError("TextOCR census binds another source")
    if payload.get("schema_fingerprint", {}).get("image_column_read") is not False:
        raise RuntimeError("TextOCR census unexpectedly read image bytes")
    return payload


def prepare_partitions(
    *,
    parquet_path: Path,
    census_path: Path,
    candidate_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if sha256_file(parquet_path) != SOURCE_SHA256:
        raise RuntimeError("TextOCR source SHA-256 changed")
    if parquet_path.stat().st_size != SOURCE_SIZE_BYTES:
        raise RuntimeError("TextOCR source size changed")
    census = _load_census(census_path)
    candidate, _ = load_candidate_bundle(candidate_root)
    if census["candidate_binding"]["stable_payload_sha256"] != candidate[
        "stable_payload_sha256"
    ]:
        raise RuntimeError("TextOCR census binds another candidate")
    if not census["power_gate"]["download_full_source_and_run_ocr"]:
        raise RuntimeError("TextOCR frozen census did not authorize full source")
    selected = {
        int(record["row_index"]): dict(record)
        for record in census["census"]["records"]
    }
    if len(selected) != int(census["census"]["selected_count"]):
        raise RuntimeError("TextOCR census contains duplicate selected rows")

    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = output_dir / "_staging_images"
    staging.mkdir(parents=True, exist_ok=True)
    parquet = pq.ParquetFile(parquet_path)
    if "image" not in parquet.schema_arrow.names:
        raise RuntimeError("TextOCR source is missing image column")
    row_index = 0
    associations: list[dict[str, Any]] = []
    seen_selected: set[int] = set()
    for batch in parquet.iter_batches(columns=["image"], batch_size=8):
        for row in batch.to_pylist():
            record = selected.get(row_index)
            if record is not None:
                seen_selected.add(row_index)
                raw = image_bytes_from_row(row)
                image_sha = sha256_bytes(raw)
                image = _decode_image(raw, row_index)
                clipped = clip_bbox(record["bbox_xyxy"], image)
                staging_file = staging / f"{image_sha}.img"
                if staging_file.exists():
                    if sha256_file(staging_file) != image_sha:
                        raise RuntimeError("TextOCR staged image hash mismatch")
                else:
                    staging_file.write_bytes(raw)
                associations.append(
                    {
                        **record,
                        "image_sha256": image_sha,
                        "image_width": image.width,
                        "image_height": image.height,
                        "bbox_xyxy_clipped": list(clipped),
                        "staging_file": str(staging_file.relative_to(output_dir)),
                    }
                )
            row_index += 1
    if seen_selected != set(selected):
        raise RuntimeError(
            f"TextOCR selected rows missing from source: "
            f"{sorted(set(selected) - seen_selected)[:10]}"
        )
    if row_index != int(census["census"]["row_count"]):
        raise RuntimeError("TextOCR full-source row count differs from census")

    by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in associations:
        by_image[str(record["image_sha256"])].append(record)
    active: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for image_sha, rows in sorted(by_image.items()):
        rows.sort(
            key=lambda row: (
                str(row["selection_rank_sha256"]),
                int(row["row_index"]),
            )
        )
        representative = rows[0]
        for duplicate in rows[1:]:
            if (
                duplicate["truth"] != representative["truth"]
                or duplicate["bbox_xyxy_clipped"]
                != representative["bbox_xyxy_clipped"]
            ):
                raise RuntimeError(
                    "duplicate TextOCR image has conflicting selected risk unit"
                )
        active.append(representative)
        if len(rows) > 1:
            duplicates.append(
                {
                    "image_sha256": image_sha,
                    "association_count": len(rows),
                    "row_indices": [int(row["row_index"]) for row in rows],
                    "canonical_row_index": int(representative["row_index"]),
                }
            )

    partition_records: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in active:
        partition_records[partition_id(record)].append(record)
    partition_summaries: list[dict[str, Any]] = []
    for partition in range(PARTITION_COUNT):
        root = output_dir / "partitions" / f"p{partition:02d}"
        images_dir = root / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        for record in sorted(
            partition_records.get(partition, []),
            key=lambda row: (str(row["image_sha256"]), int(row["row_index"])),
        ):
            source = output_dir / record["staging_file"]
            destination = images_dir / f"{record['image_sha256']}.img"
            shutil.copyfile(source, destination)
            cleaned = {
                key: value
                for key, value in record.items()
                if key != "staging_file"
            }
            cleaned["image_file"] = str(destination.relative_to(root))
            cleaned["partition_id"] = partition
            cleaned["macrofold_id"] = macrofold_id(record)
            cleaned["counterfactual_claim"] = mutate_one_digit(
                str(record["truth"]),
                (
                    f"{DATASET_REVISION}:{record['row_index']}:"
                    f"{record['selection_rank_sha256']}"
                ),
            )
            records.append(cleaned)
        manifest = stable_payload(
            {
                "schema": PARTITION_MANIFEST_SCHEMA,
                "dataset": {
                    "id": DATASET_ID,
                    "revision": DATASET_REVISION,
                    "source_path": SOURCE_PATH,
                    "source_sha256": SOURCE_SHA256,
                },
                "candidate_binding": {
                    "candidate_id": candidate["candidate_id"],
                    "stable_payload_sha256": candidate[
                        "stable_payload_sha256"
                    ],
                    "source_commit": candidate["source_commit"],
                },
                "census_binding": {
                    "stable_payload_sha256": census[
                        "stable_payload_sha256"
                    ],
                    "selected_record_set_sha256": census["census"][
                        "selected_record_set_sha256"
                    ],
                },
                "partition_id": partition,
                "partition_count": PARTITION_COUNT,
                "record_count": len(records),
                "records": records,
            },
            "stable_payload_sha256",
        )
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        write_hash_manifest(root)
        partition_summaries.append(
            {
                "partition_id": partition,
                "macrofold_id": partition % MACROFOLD_COUNT,
                "record_count": len(records),
                "stable_payload_sha256": manifest[
                    "stable_payload_sha256"
                ],
            }
        )
    shutil.rmtree(staging)
    active_count = len(active)
    projected_accepted = active_count * (472 / 1720)
    run_ocr = bool(
        active_count >= MINIMUM_SELECTED
        and projected_accepted >= MINIMUM_ACCEPTED
    )
    protocol = stable_payload(
        {
            "schema": PREPARATION_SCHEMA,
            "status": "PREPARED_AFTER_CENSUS_BEFORE_TEXTOCR_OCR",
            "dataset": {
                "id": DATASET_ID,
                "revision": DATASET_REVISION,
                "source_path": SOURCE_PATH,
                "source_sha256": SOURCE_SHA256,
                "source_size_bytes": SOURCE_SIZE_BYTES,
            },
            "candidate_binding": {
                "candidate_id": candidate["candidate_id"],
                "stable_payload_sha256": candidate[
                    "stable_payload_sha256"
                ],
                "source_commit": candidate["source_commit"],
            },
            "census_binding": {
                "stable_payload_sha256": census["stable_payload_sha256"],
                "selected_record_set_sha256": census["census"][
                    "selected_record_set_sha256"
                ],
            },
            "execution": {
                "source_rows": row_index,
                "selected_associations": len(associations),
                "unique_physical_images": active_count,
                "duplicate_associations_removed": len(associations)
                - active_count,
                "duplicate_groups": duplicates,
                "partition_count": PARTITION_COUNT,
                "macrofold_count": MACROFOLD_COUNT,
                "partitions": partition_summaries,
                "active_risk_unit_set_sha256": sha256_bytes(
                    canonical_json(
                        [
                            {
                                "image_sha256": row["image_sha256"],
                                "truth": row["truth"],
                                "bbox_xyxy_clipped": row[
                                    "bbox_xyxy_clipped"
                                ],
                                "selection_rank_sha256": row[
                                    "selection_rank_sha256"
                                ],
                            }
                            for row in sorted(
                                active,
                                key=lambda item: str(item["image_sha256"]),
                            )
                        ]
                    ).encode("utf-8")
                ),
            },
            "power_gate": {
                "minimum_selected": MINIMUM_SELECTED,
                "minimum_accepted": MINIMUM_ACCEPTED,
                "selected_available": active_count,
                "selected_pass": active_count >= MINIMUM_SELECTED,
                "development_acceptance_rate": 472 / 1720,
                "projected_accepted": projected_accepted,
                "projected_accepted_pass": projected_accepted
                >= MINIMUM_ACCEPTED,
                "run_ocr": run_ocr,
            },
            "decision": {
                "full_source_verified": True,
                "physical_deduplication_complete": True,
                "ocr_executed": False,
                "candidate_inference_executed": False,
                "external_certificate_claimed": False,
                "production_ready": False,
                "automatic_production_change": False,
            },
            "constraints": {
                "external_spend_usd": 0,
                "gcloud_used": False,
                "gpu_used": False,
                "paid_api_used": False,
                "production_modified": False,
            },
        },
        "stable_payload_sha256",
    )
    (output_dir / "protocol.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    write_hash_manifest(output_dir)
    return protocol


def _policy_row(
    *,
    claim: str,
    prediction: str,
    minimum_probability: float,
    matched: Mapping[str, Any],
    guard: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "candidate": {
            "eligible": True,
            "claim": claim,
            "prediction": prediction,
            "minimum_mean_probability": minimum_probability,
            "matched": dict(matched),
            "guard": dict(guard),
        }
    }


def evaluate_record(
    *,
    image: Image.Image,
    record: Mapping[str, Any],
    model: Any,
    detector_configuration: Mapping[str, Any],
) -> dict[str, Any]:
    truth = str(record["truth"])
    bbox = tuple(int(value) for value in record["bbox_xyxy_clipped"])
    counterfactual = str(record["counterfactual_claim"])
    baseline_tokens, baseline_runtime = tesseract_tokens(image)
    baseline_matched = match_ocr_claim(bbox, baseline_tokens)
    baseline_claim, baseline_eligible, baseline_reason = eligibility(
        truth, baseline_matched
    )
    raw_candidates: list[dict[str, Any]] = []
    psm_runtime: dict[str, Any] = {}
    for psm in detector_configuration["psms"]:
        candidates, runtime = tesseract_numeric_candidates(image, int(psm))
        raw_candidates.extend(candidates)
        psm_runtime[str(psm)] = runtime
    resolved = resolved_tokens(
        cluster_candidates(raw_candidates), detector_configuration
    )
    matched = match_ocr_claim(bbox, resolved)
    claim, eligible, reason = eligibility(truth, matched)
    prediction = ""
    minimum_probability: float | None = None
    guard: dict[str, Any] | None = None
    crop_sha256: str | None = None
    crop_coordinates: list[int] | None = None
    forest_seconds = 0.0
    final_prediction: str | None = None
    counterfactual_prediction = ""
    counterfactual_minimum_probability: float | None = None
    counterfactual_accepted = False
    if eligible:
        box = crop_box(image, matched["bbox"], margin=2)
        crop_coordinates = list(box)
        crop = image.crop(box)
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG", optimize=False)
        crop_sha256 = sha256_bytes(buffer.getvalue())
        started = time.perf_counter()
        decision = infer_claim(model, crop, claim, threshold=0.25)
        forest_seconds += time.perf_counter() - started
        prediction = str(decision.get("prediction") or "")
        minimum_probability = float(
            decision.get("minimum_mean_probability") or 0.0
        )
        guard = crop_guard_readings(crop)
        final_prediction = predict_v6_gate_completion(
            _policy_row(
                claim=claim,
                prediction=prediction,
                minimum_probability=minimum_probability,
                matched=matched,
                guard=guard,
            )
        )
        started = time.perf_counter()
        counter_decision = infer_claim(
            model, crop, counterfactual, threshold=0.25
        )
        forest_seconds += time.perf_counter() - started
        counterfactual_prediction = str(
            counter_decision.get("prediction") or ""
        )
        counterfactual_minimum_probability = float(
            counter_decision.get("minimum_mean_probability") or 0.0
        )
        counterfactual_accepted = (
            predict_v6_gate_completion(
                _policy_row(
                    claim=counterfactual,
                    prediction=counterfactual_prediction,
                    minimum_probability=counterfactual_minimum_probability,
                    matched=matched,
                    guard=guard,
                )
            )
            is not None
        )
    return {
        "row_index": int(record["row_index"]),
        "image_sha256": record["image_sha256"],
        "partition_id": int(record["partition_id"]),
        "macrofold_id": int(record["macrofold_id"]),
        "truth": truth,
        "bbox_xyxy": list(bbox),
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
            "claim": claim,
            "eligible": eligible,
            "reason": reason,
            "matched": matched,
            "forest_prediction": prediction,
            "minimum_mean_probability": minimum_probability,
            "guard": guard,
            "final_prediction": final_prediction,
            "accepted": final_prediction is not None,
            "correct_accept": final_prediction == truth,
            "false_accept": bool(
                final_prediction is not None and final_prediction != truth
            ),
            "crop_box": crop_coordinates,
            "crop_sha256": crop_sha256,
            "forest_seconds": forest_seconds,
            "psm_runtime": psm_runtime,
        },
        "counterfactual": {
            "claim": counterfactual,
            "forest_prediction": counterfactual_prediction,
            "minimum_mean_probability": (
                counterfactual_minimum_probability
            ),
            "accepted": counterfactual_accepted,
        },
    }


def evaluate_partition(
    *,
    partition_root: Path,
    candidate_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    verify_hash_manifest(partition_root)
    manifest = json.loads(
        (partition_root / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("schema") != PARTITION_MANIFEST_SCHEMA:
        raise RuntimeError("unexpected TextOCR partition manifest schema")
    if not verify_stable_payload(manifest, "stable_payload_sha256"):
        raise RuntimeError("TextOCR partition manifest stable replay failed")
    candidate, model = load_candidate_bundle(candidate_root)
    if manifest["candidate_binding"]["stable_payload_sha256"] != candidate[
        "stable_payload_sha256"
    ]:
        raise RuntimeError("TextOCR partition binds another candidate")
    observations: list[dict[str, Any]] = []
    baseline_seconds: list[float] = []
    forest_seconds: list[float] = []
    psm_seconds: Counter[str] = Counter()
    psm_timeouts: Counter[str] = Counter()
    for index, record in enumerate(manifest["records"]):
        image_path = partition_root / record["image_file"]
        if sha256_file(image_path) != record["image_sha256"]:
            raise RuntimeError("TextOCR partition image hash mismatch")
        image = _decode_image(image_path.read_bytes(), int(record["row_index"]))
        observation = evaluate_record(
            image=image,
            record=record,
            model=model,
            detector_configuration=candidate["detector"]["configuration"],
        )
        observations.append(observation)
        baseline_seconds.append(
            float(observation["baseline"]["runtime"]["wall_seconds"])
        )
        forest_seconds.append(
            float(observation["candidate"]["forest_seconds"])
        )
        for psm, runtime in observation["candidate"][
            "psm_runtime"
        ].items():
            psm_seconds[psm] += float(runtime["wall_seconds"])
            psm_timeouts[psm] += int(bool(runtime["timeout"]))
        print(
            json.dumps(
                {
                    "partition_id": manifest["partition_id"],
                    "processed": index + 1,
                    "records": manifest["record_count"],
                    "accepted": sum(
                        row["candidate"]["accepted"]
                        for row in observations
                    ),
                    "false_accepted": sum(
                        row["candidate"]["false_accept"]
                        for row in observations
                    ),
                    "counterfactual_accepted": sum(
                        row["counterfactual"]["accepted"]
                        for row in observations
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    report = stable_payload(
        {
            "schema": PARTITION_REPORT_SCHEMA,
            "dataset": manifest["dataset"],
            "candidate_binding": manifest["candidate_binding"],
            "census_binding": manifest["census_binding"],
            "partition_id": manifest["partition_id"],
            "partition_count": manifest["partition_count"],
            "record_count": len(observations),
            "descriptive": {
                "baseline_eligible": sum(
                    row["baseline"]["eligible"] for row in observations
                ),
                "baseline_false": sum(
                    row["baseline"]["eligible"]
                    and not row["baseline"]["claim_correct"]
                    for row in observations
                ),
                "accepted": sum(
                    row["candidate"]["accepted"] for row in observations
                ),
                "accepted_false": sum(
                    row["candidate"]["false_accept"]
                    for row in observations
                ),
                "counterfactual_accepted": sum(
                    row["counterfactual"]["accepted"]
                    for row in observations
                ),
                "median_baseline_seconds": (
                    statistics.median(baseline_seconds)
                    if baseline_seconds
                    else None
                ),
                "p95_baseline_seconds": p95(baseline_seconds),
                "median_forest_ms": (
                    statistics.median(forest_seconds) * 1000.0
                    if forest_seconds
                    else None
                ),
                "p95_forest_ms": (
                    p95(forest_seconds) * 1000.0
                    if forest_seconds
                    else None
                ),
                "psm_wall_seconds": dict(sorted(psm_seconds.items())),
                "psm_timeouts": dict(sorted(psm_timeouts.items())),
            },
            "observations": observations,
            "decision": {
                "partition_execution_complete": True,
                "aggregate_exact_certificate_required": True,
                "external_certificate_claimed_at_partition_level": False,
                "production_ready": False,
                "automatic_production_change": False,
            },
            "constraints": {
                "external_spend_usd": 0,
                "gcloud_used": False,
                "gpu_used": False,
                "paid_api_used": False,
                "production_modified": False,
            },
        },
        "stable_payload_sha256",
    )
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "partition_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
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
    baseline = [row for row in selected if row["baseline"]["eligible"]]
    baseline_false = sum(
        not row["baseline"]["claim_correct"] for row in baseline
    )
    accepted = [row for row in selected if row["candidate"]["accepted"]]
    accepted_false = sum(
        row["candidate"]["false_accept"] for row in accepted
    )
    counterfactual_false = sum(
        row["counterfactual"]["accepted"] for row in selected
    )
    baseline_lower = (
        clopper_pearson_lower(
            baseline_false, len(baseline), ALPHA_PER_LEG
        )
        if baseline
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
        clopper_pearson_lower(
            len(accepted), len(selected), ALPHA_PER_LEG
        )
        if selected
        else 0.0
    )
    counterfactual_upper = (
        clopper_pearson_upper(
            counterfactual_false, len(selected), ALPHA_PER_LEG
        )
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
        and coverage_lower >= MINIMUM_COVERAGE_LOWER
        and candidate_upper <= baseline_lower / TARGET_REDUCTION
        and counterfactual_upper <= COUNTERFACTUAL_MAXIMUM_UPPER
    )
    return {
        "selected": len(selected),
        "baseline_eligible": len(baseline),
        "baseline_false": baseline_false,
        "accepted": len(accepted),
        "accepted_false": accepted_false,
        "counterfactual_false": counterfactual_false,
        "baseline_lower": baseline_lower,
        "candidate_upper": candidate_upper,
        "coverage_lower": coverage_lower,
        "counterfactual_upper": counterfactual_upper,
        "reduction_lower": reduction_lower,
        "minimum_selected_required": minimum_selected,
        "minimum_accepted_required": minimum_accepted,
        "pass": passed,
    }


def _scaled(required: int, subset: int, full: int) -> int:
    return max(1, math.ceil(required * subset / max(full, 1)))


def aggregate_reports(
    *,
    protocol_path: Path,
    report_roots: Sequence[Path],
    output_dir: Path,
) -> dict[str, Any]:
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("schema") != PREPARATION_SCHEMA:
        raise RuntimeError("unexpected TextOCR prepared protocol schema")
    if not verify_stable_payload(protocol, "stable_payload_sha256"):
        raise RuntimeError("TextOCR prepared protocol stable replay failed")
    reports: dict[int, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for root in report_roots:
        verify_hash_manifest(root)
        report = json.loads(
            (root / "partition_report.json").read_text(encoding="utf-8")
        )
        if report.get("schema") != PARTITION_REPORT_SCHEMA:
            raise RuntimeError("unexpected TextOCR partition report schema")
        if not verify_stable_payload(report, "stable_payload_sha256"):
            raise RuntimeError("TextOCR partition report stable replay failed")
        partition = int(report["partition_id"])
        if partition in reports:
            raise RuntimeError(f"duplicate TextOCR partition report: {partition}")
        if report["candidate_binding"] != protocol["candidate_binding"]:
            raise RuntimeError("TextOCR partition binds another candidate")
        if report["census_binding"] != protocol["census_binding"]:
            raise RuntimeError("TextOCR partition binds another census")
        reports[partition] = report
        observations.extend(report["observations"])
    if set(reports) != set(range(PARTITION_COUNT)):
        raise RuntimeError(
            f"TextOCR aggregate requires all partitions: {sorted(reports)}"
        )
    if len(observations) != int(
        protocol["execution"]["unique_physical_images"]
    ):
        raise RuntimeError("TextOCR aggregate denominator differs from protocol")
    image_hashes = [str(row["image_sha256"]) for row in observations]
    if len(set(image_hashes)) != len(image_hashes):
        raise RuntimeError("duplicate TextOCR physical images reached aggregate")
    overall = exact_summary(observations)
    folds = []
    for held_out in range(MACROFOLD_COUNT):
        subset = [
            row for row in observations if int(row["macrofold_id"]) != held_out
        ]
        folds.append(
            {
                "held_out_macrofold": held_out,
                "summary": exact_summary(
                    subset,
                    minimum_selected=_scaled(
                        MINIMUM_SELECTED, len(subset), len(observations)
                    ),
                    minimum_accepted=_scaled(
                        MINIMUM_ACCEPTED, len(subset), len(observations)
                    ),
                ),
            }
        )
    stability_passes = sum(bool(fold["summary"]["pass"]) for fold in folds)
    stability_fraction = stability_passes / len(folds)
    stability_pass = bool(
        stability_fraction >= MINIMUM_STABILITY_PASS_FRACTION
    )
    external_pass = bool(overall["pass"] and stability_pass)
    if external_pass:
        verdict = "PASS_EXTERNAL_TEXTOCR_NUMERIC_10X_CERTIFICATE"
    elif overall["selected"] < MINIMUM_SELECTED:
        verdict = "TEXTOCR_UNDERPOWERED_SELECTED_DENOMINATOR"
    elif overall["baseline_false"] == 0:
        verdict = "TEXTOCR_BASELINE_TOO_CLEAN_TO_CERTIFY"
    elif not overall["pass"]:
        verdict = "TEXTOCR_EXTERNAL_TENFOLD_BOUND_NOT_REACHED"
    else:
        verdict = "TEXTOCR_EXTERNAL_MACROFOLD_STABILITY_FAILED"
    aggregate = stable_payload(
        {
            "schema": AGGREGATE_SCHEMA,
            "dataset": protocol["dataset"],
            "candidate_binding": protocol["candidate_binding"],
            "census_binding": protocol["census_binding"],
            "protocol_binding": {
                "stable_payload_sha256": protocol[
                    "stable_payload_sha256"
                ],
                "active_risk_unit_set_sha256": protocol["execution"][
                    "active_risk_unit_set_sha256"
                ],
            },
            "execution": {
                "selected_unique_images": len(observations),
                "partition_count": PARTITION_COUNT,
                "macrofold_count": MACROFOLD_COUNT,
                "duplicate_associations_removed": protocol["execution"][
                    "duplicate_associations_removed"
                ],
                "ocr_timeouts": sum(
                    sum(
                        int(value)
                        for value in report["descriptive"][
                            "psm_timeouts"
                        ].values()
                    )
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
                "simultaneous_95pct_coverage_lower": overall[
                    "coverage_lower"
                ],
                "certified_error_reduction_lower": overall[
                    "reduction_lower"
                ],
            },
            "counterfactual": {
                "cases": overall["selected"],
                "false_accepts": overall["counterfactual_false"],
                "simultaneous_95pct_upper": overall[
                    "counterfactual_upper"
                ],
                "method": "same-crop equal-length injected claim replay",
            },
            "stability": {
                "macrofolds": MACROFOLD_COUNT,
                "passes": stability_passes,
                "pass_fraction": stability_fraction,
                "minimum_pass_fraction": MINIMUM_STABILITY_PASS_FRACTION,
                "pass": stability_pass,
                "details": folds,
            },
            "decision": {
                "external_validation_complete": True,
                "candidate_bound_before_textocr_outcomes": True,
                "pass_statistical_10x": external_pass,
                "tenfold_bound_reached": bool(overall["pass"]),
                "macrofold_stability_passed": stability_pass,
                "automatic_production_change": False,
                "honduras_production_readiness_claimed": False,
                "general_ocr_superiority_claimed": False,
                "verdict": verdict,
            },
            "constraints": {
                "external_spend_usd": 0,
                "gcloud_used": False,
                "gpu_used": False,
                "paid_api_used": False,
                "production_modified": False,
            },
        },
        "stable_payload_sha256",
    )
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "textocr_external_aggregate.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    write_hash_manifest(output_dir)
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--parquet", required=True, type=Path)
    prepare.add_argument("--census", required=True, type=Path)
    prepare.add_argument("--candidate-root", required=True, type=Path)
    prepare.add_argument("--output-dir", required=True, type=Path)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--partition-root", required=True, type=Path)
    evaluate.add_argument("--candidate-root", required=True, type=Path)
    evaluate.add_argument("--output-dir", required=True, type=Path)

    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--protocol", required=True, type=Path)
    aggregate.add_argument("report_roots", nargs="+", type=Path)
    aggregate.add_argument("--output-dir", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_partitions(
            parquet_path=args.parquet,
            census_path=args.census,
            candidate_root=args.candidate_root,
            output_dir=args.output_dir,
        )
    elif args.command == "evaluate":
        result = evaluate_partition(
            partition_root=args.partition_root,
            candidate_root=args.candidate_root,
            output_dir=args.output_dir,
        )
    else:
        result = aggregate_reports(
            protocol_path=args.protocol,
            report_roots=args.report_roots,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
