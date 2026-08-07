"""Authorized OpenVINO v7 partition executor with persisted outcome quarantine."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from .core import mutate_one_digit, sha256_bytes, sha256_file
from .openvino_full_gate_contract_v7 import (
    CANDIDATE_STABLE_PAYLOAD_SHA256,
    MODEL_ARTIFACT_ID,
    MODEL_CANDIDATE_STABLE_SHA256,
    MODEL_SHA256,
    MODEL_ZIP_SHA256,
    PARTITION_COUNT,
    PARTITION_REPORT_SCHEMA,
    SCIENTIFIC_MANIFEST_SHA256,
    SOURCE_REVISION,
    SOURCE_URL,
    _read_jsonl,
    _write_json,
    _write_jsonl,
    canonical_pixel_sha256,
    stable_payload,
    verify_execution_authorization,
    verify_manifest_bundle,
    write_hash_manifest,
)
from .openvino_full_gate_prepare_v7 import (
    _duckdb_connection,
    _image_bytes,
    _insert_manifest_table,
    _quote_sql,
    prepare_registry_from_source,
)
from .openvino_full_gate_registry_v7 import (
    _image_id_from_path,
    verify_registry_bundle,
)


def _load_model(model_zip: Path, extraction_root: Path) -> tuple[Any, dict[str, Any]]:
    """Load the exact digit forest through the already-frozen loader."""
    import zipfile

    if sha256_file(model_zip) != MODEL_ZIP_SHA256:
        raise RuntimeError("model artifact ZIP SHA-256 mismatch")
    with zipfile.ZipFile(model_zip) as archive:
        names = archive.namelist()
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise RuntimeError("unsafe model ZIP member")
        archive.extractall(extraction_root)
    candidates = list(extraction_root.rglob("frozen_candidate.json"))
    if len(candidates) != 1:
        raise RuntimeError("exactly one frozen model candidate is required")
    model_root = candidates[0].parent
    from .numeric_digit_forest import load_frozen_candidate

    candidate, model = load_frozen_candidate(model_root)
    model_paths = list(model_root.rglob("digit_forest.joblib"))
    if len(model_paths) != 1 or sha256_file(model_paths[0]) != MODEL_SHA256:
        raise RuntimeError("digit forest model SHA-256 mismatch")
    if (
        candidate.get("candidate_id") != "digit-forest-v3"
        or candidate.get("stable_payload_sha256")
        != MODEL_CANDIDATE_STABLE_SHA256
        or len(model.estimators_) != 500
    ):
        raise RuntimeError("digit forest candidate contract failed")
    return model, {
        "artifact_id": MODEL_ARTIFACT_ID,
        "artifact_zip_sha256": MODEL_ZIP_SHA256,
        "model_sha256": MODEL_SHA256,
        "candidate_stable_payload_sha256": MODEL_CANDIDATE_STABLE_SHA256,
        "tree_count": len(model.estimators_),
    }


def _fetch_partition_images(
    connection: Any,
    records: Sequence[Mapping[str, Any]],
    staging_dir: Path,
) -> list[dict[str, Any]]:
    _insert_manifest_table(connection, records)
    source = _quote_sql(SOURCE_URL)
    rows = connection.execute(
        "SELECT r.row_index, r.image_id, r.partition, r.selection_rank_sha256, "
        "p.image.path::VARCHAR, p.image.bytes "
        f"FROM read_parquet({source}, file_row_number=true) p "
        "JOIN requested_rows r ON r.row_index = p.file_row_number "
        "ORDER BY r.row_index"
    ).fetchall()
    expected = {int(row["row_index"]): row for row in records}
    if len(rows) != len(records):
        raise RuntimeError("partition image query denominator drift")
    from PIL import Image

    shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True)
    result: list[dict[str, Any]] = []
    for row_index, image_id, partition, rank, path, raw_value in rows:
        record = expected.get(int(row_index))
        raw = _image_bytes(raw_value)
        if (
            record is None
            or str(record["image_id"]) != image_id
            or _image_id_from_path(path) != image_id
            or sha256_bytes(raw) != record["encoded_sha256"]
        ):
            raise RuntimeError("partition source identity/hash drift")
        try:
            with Image.open(io.BytesIO(raw)) as opened:
                image = opened.convert("RGB")
        except Exception as exc:
            raise RuntimeError(f"partition image decode failed: {row_index}") from exc
        if canonical_pixel_sha256(image) != record["pixel_sha256"]:
            raise RuntimeError("partition decoded-pixel SHA-256 drift")
        image_file = staging_dir / f"{record['encoded_sha256']}.img"
        if image_file.exists():
            raise RuntimeError("duplicate encoded image reached active partition")
        image_file.write_bytes(raw)
        result.append({**record, "image_file": str(image_file)})
        del raw
    return result


def _run_outcome_blind_detector(
    images: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    from PIL import Image
    from .cord_consensus_detector_v4 import (
        PSM_MODES,
        cluster_candidates,
        resolved_tokens,
        tesseract_numeric_candidates,
    )
    from .cord_detector_crops_v4 import SELECTED_CONFIGURATION

    outputs: dict[int, dict[str, Any]] = {}
    for ordinal, record in enumerate(images, start=1):
        with Image.open(Path(str(record["image_file"]))) as opened:
            image = opened.convert("RGB")
        raw_candidates: list[dict[str, Any]] = []
        runtimes: dict[str, Any] = {}
        started = time.perf_counter()
        for psm in PSM_MODES:
            candidates, runtime = tesseract_numeric_candidates(image, int(psm))
            raw_candidates.extend(candidates)
            runtimes[str(psm)] = runtime
        tokens = resolved_tokens(
            cluster_candidates(raw_candidates), SELECTED_CONFIGURATION
        )
        outputs[int(record["row_index"])] = {
            "tokens": tokens,
            "raw_candidate_count": len(raw_candidates),
            "resolved_token_count": len(tokens),
            "psm_runtime": runtimes,
            "wall_seconds": time.perf_counter() - started,
            "terminal": all(
                not bool(value.get("timeout")) for value in runtimes.values()
            ),
        }
        print(
            json.dumps(
                {
                    "phase": "partition_outcome_blind_detector",
                    "ordinal": ordinal,
                    "rows": len(images),
                    "row_index": record["row_index"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if set(outputs) != {int(record["row_index"]) for record in images}:
        raise RuntimeError("outcome-blind detector barrier is incomplete")
    return outputs


def _fetch_partition_annotations(
    records: Sequence[Mapping[str, Any]],
) -> dict[int, tuple[Any, Any, Any, Any]]:
    connection = _duckdb_connection()
    _insert_manifest_table(connection, records)
    source = _quote_sql(SOURCE_URL)
    rows = connection.execute(
        "SELECT r.row_index, p.texts, p.bboxes, p.polygons, p.num_text_regions "
        f"FROM read_parquet({source}, file_row_number=true) p "
        "JOIN requested_rows r ON r.row_index = p.file_row_number "
        "ORDER BY r.row_index"
    ).fetchall()
    if len(rows) != len(records):
        raise RuntimeError("partition annotation query denominator drift")
    return {
        int(row_index): (texts, bboxes, polygons, num_regions)
        for row_index, texts, bboxes, polygons, num_regions in rows
    }


def _score_partition_after_barrier(
    images: Sequence[MutableMapping[str, Any]],
    detector_outputs: Mapping[int, Mapping[str, Any]],
    annotations: Mapping[int, tuple[Any, Any, Any, Any]],
    model: Any,
) -> list[dict[str, Any]]:
    from PIL import Image
    from .cord_consensus_detector_v4 import crop_guard_readings
    from .numeric_consensus_policy_v7 import (
        FOREST_MINIMUM_MEAN_PROBABILITY,
        inference_eligibility,
        predict_v7_claim_verifier,
    )
    from .numeric_digit_forest import infer_claim
    from .sroie_natural_holdout import crop_box, match_ocr_claim
    from .textocr_adapter_v6 import select_numeric_annotation

    results: list[dict[str, Any]] = []
    for record in images:
        row_index = int(record["row_index"])
        texts, bboxes, polygons, num_regions = annotations[row_index]
        selected, _ = select_numeric_annotation(
            row_index=row_index,
            texts=texts,
            bboxes=bboxes,
            polygons=polygons,
            num_text_regions=num_regions,
        )
        if (
            selected is None
            or selected.get("selection_rank_sha256")
            != record["selection_rank_sha256"]
        ):
            raise RuntimeError("post-barrier annotation selection drift")
        image_file = Path(str(record["image_file"]))
        with Image.open(image_file) as opened:
            image = opened.convert("RGB")
        detector = detector_outputs[row_index]
        matched = match_ocr_claim(selected["bbox_xyxy"], detector["tokens"])
        claim, eligible, reason = inference_eligibility(matched)
        truth = str(selected["truth"])
        forest: Mapping[str, Any] | None = None
        guard: Mapping[str, Any] | None = None
        final_prediction: str | None = None
        verifier_seconds = 0.0
        counterfactual = mutate_one_digit(
            truth,
            f"{SOURCE_REVISION}:{row_index}:{selected['selection_rank_sha256']}",
        )
        counterfactual_prediction: str | None = None
        counterfactual_forest: Mapping[str, Any] | None = None
        if eligible and matched is not None:
            box = crop_box(image, matched["bbox"], margin=2)
            crop = image.crop(box)
            started = time.perf_counter()
            forest = infer_claim(
                model,
                crop,
                claim,
                threshold=FOREST_MINIMUM_MEAN_PROBABILITY,
            )
            guard = crop_guard_readings(crop)
            final_prediction = predict_v7_claim_verifier(
                {
                    "candidate": {
                        "claim": claim,
                        "prediction": forest.get("prediction"),
                        "minimum_mean_probability": forest.get(
                            "minimum_mean_probability"
                        ),
                        "matched": matched,
                        "guard": guard,
                    }
                }
            )
            counterfactual_forest = infer_claim(
                model,
                crop,
                counterfactual,
                threshold=FOREST_MINIMUM_MEAN_PROBABILITY,
            )
            counterfactual_prediction = predict_v7_claim_verifier(
                {
                    "candidate": {
                        "claim": counterfactual,
                        "prediction": counterfactual_forest.get("prediction"),
                        "minimum_mean_probability": counterfactual_forest.get(
                            "minimum_mean_probability"
                        ),
                        "matched": matched,
                        "guard": guard,
                    }
                }
            )
            verifier_seconds = time.perf_counter() - started
        results.append(
            {
                "row_index": row_index,
                "image_id": record["image_id"],
                "partition_id": int(record["partition"]),
                "macrofold_id": int(record["partition"]) // 3,
                "encoded_sha256": record["encoded_sha256"],
                "pixel_sha256": record["pixel_sha256"],
                "truth": truth,
                "selection_rank_sha256": selected["selection_rank_sha256"],
                "terminal": True,
                "outcome_quarantine": {
                    "detector_completed_before_annotation_query": True,
                    "annotation_query_after_partition_detector_barrier": True,
                },
                "detector": {
                    "raw_candidates": detector["raw_candidate_count"],
                    "resolved_tokens": detector["resolved_token_count"],
                    "psm_runtime": detector["psm_runtime"],
                    "all_calls_terminal": detector["terminal"],
                },
                "baseline": {
                    "claim": claim,
                    "eligible": eligible,
                    "reason": reason,
                    "claim_correct": bool(eligible and claim == truth),
                    "wall_seconds": detector["wall_seconds"],
                },
                "candidate": {
                    "forest_prediction": (
                        forest.get("prediction") if forest is not None else None
                    ),
                    "minimum_mean_probability": (
                        forest.get("minimum_mean_probability")
                        if forest is not None
                        else None
                    ),
                    "guard": guard,
                    "final_prediction": final_prediction,
                    "accepted": final_prediction is not None,
                    "false_accept": bool(
                        final_prediction is not None and final_prediction != truth
                    ),
                    "verifier_wall_seconds": verifier_seconds,
                },
                "counterfactual": {
                    "claim": counterfactual,
                    "forest_prediction": (
                        counterfactual_forest.get("prediction")
                        if counterfactual_forest is not None
                        else None
                    ),
                    "accepted": counterfactual_prediction is not None,
                },
            }
        )
        image_file.unlink(missing_ok=True)
        record.pop("image_file", None)
    return results


def evaluate_partition_from_source(
    *,
    manifest_root: Path,
    registry_root: Path,
    partition: int,
    model_zip: Path,
    authorization_path: Path,
    authorization_sha256: str,
    output_dir: Path,
) -> dict[str, Any]:
    if not 0 <= partition < PARTITION_COUNT:
        raise RuntimeError("partition must lie in [0, 11]")
    authorization = verify_execution_authorization(
        authorization_path, authorization_sha256, "EVALUATE_PARTITIONS"
    )
    verify_manifest_bundle(manifest_root)
    registry_summary = verify_registry_bundle(registry_root)
    if not registry_summary["evaluation_authorized"]:
        raise RuntimeError("physical registry did not authorize evaluation")
    registry_authorization = registry_summary.get("authorization_binding")
    if (
        not isinstance(registry_authorization, Mapping)
        or registry_authorization.get("execution_id")
        != authorization["execution_id"]
        or registry_authorization.get("authorization_nonce_sha256")
        != authorization["authorization_nonce_sha256"]
        or registry_authorization.get("authorization_stable_payload_sha256")
        != authorization["stable_payload_sha256"]
    ):
        raise RuntimeError("registry and evaluation authorization bindings differ")
    records = _read_jsonl(
        Path(registry_root) / f"active_partition_{partition:02d}.jsonl"
    )
    if len(records) != registry_summary["partition_counts"][partition]:
        raise RuntimeError("active partition denominator drift")
    from .openvino_smoke_v7 import runtime_identity, verify_source_identity

    source_identity = verify_source_identity()
    runtime = runtime_identity()
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="openvino-v7-model-") as temporary:
        model, model_identity = _load_model(model_zip, Path(temporary))
        image_connection = _duckdb_connection()
        images = _fetch_partition_images(
            image_connection, records, output_dir / "_staged_images"
        )
        detector_outputs = _run_outcome_blind_detector(images)
        barrier_rows = [
            {
                "row_index": row_index,
                "tokens": value["tokens"],
                "raw_candidate_count": value["raw_candidate_count"],
                "resolved_token_count": value["resolved_token_count"],
                "psm_runtime": value["psm_runtime"],
                "wall_seconds": value["wall_seconds"],
                "terminal": value["terminal"],
            }
            for row_index, value in sorted(detector_outputs.items())
        ]
        barrier_path = output_dir / "detector_barrier.jsonl"
        _write_jsonl(barrier_path, barrier_rows)
        detector_barrier = sha256_file(barrier_path)
        # The annotation query is deliberately below the complete, persisted
        # detector barrier. Do not reorder these statements.
        annotations = _fetch_partition_annotations(records)
        observations = _score_partition_after_barrier(
            images, detector_outputs, annotations, model
        )
        shutil.rmtree(output_dir / "_staged_images", ignore_errors=True)
    report = stable_payload(
        {
            "schema": PARTITION_REPORT_SCHEMA,
            "partition_id": partition,
            "partition_count": PARTITION_COUNT,
            "record_count": len(observations),
            "candidate_stable_payload_sha256": CANDIDATE_STABLE_PAYLOAD_SHA256,
            "registry_stable_payload_sha256": registry_summary[
                "stable_payload_sha256"
            ],
            "scientific_manifest_sha256": SCIENTIFIC_MANIFEST_SHA256,
            "authorization_binding": registry_authorization,
            "source_identity": source_identity,
            "runtime": runtime,
            "model": model_identity,
            "executor_source_sha256": sha256_file(Path(__file__)),
            "detector_barrier_sha256": detector_barrier,
            "detector_barrier_rows": len(barrier_rows),
            "annotation_query_executed_after_detector_barrier": True,
            "execution_complete": len(observations) == len(records),
            "observations": observations,
            "constraints": {
                "automatic_production_change": False,
                "retuning_authorized": False,
                "post_outcome_retry_authorized": False,
                "gpu_used": False,
                "paid_ocr_api_used": False,
            },
        }
    )
    _write_json(output_dir / "partition_report.json", report)
    write_hash_manifest(output_dir)
    return report
