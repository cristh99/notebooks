"""Preregistered 16-row OpenVINO v7 engineering smoke.

This executor opens only the frozen 16 image rows after runtime and source checks.
All full-image detector outputs are completed before annotation text/geometry is
queried, preserving the annotation quarantine. It emits engineering evidence
only; it cannot authorize or launch the 20,613-row scientific gate.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import duckdb
import joblib
import numpy as np
import PIL
import pyarrow
import pytesseract
import sklearn
from PIL import Image

from ocr_real_risk_v1.cord_consensus_detector_v4 import (
    PSM_MODES,
    cluster_candidates,
    crop_guard_readings,
    resolved_tokens,
    tesseract_numeric_candidates,
)
from ocr_real_risk_v1.cord_detector_crops_v4 import SELECTED_CONFIGURATION
from ocr_real_risk_v1.core import canonical_json, sha256_bytes, sha256_file
from ocr_real_risk_v1.numeric_consensus_policy_v7 import (
    FOREST_MINIMUM_MEAN_PROBABILITY,
    inference_eligibility,
    policy_manifest,
    predict_v7_claim_verifier,
)
from ocr_real_risk_v1.numeric_digit_forest import (
    infer_claim,
    load_frozen_candidate,
)
from ocr_real_risk_v1.sroie_natural_holdout import crop_box, match_ocr_claim
from ocr_real_risk_v1.textocr_adapter_v6 import select_numeric_annotation

SCHEMA = "eaat.openvino_v7_engineering_smoke/v1"
STATUS_PASS = "SMOKE_PASS_ENGINEERING_ONLY"
STATUS_FAIL = "SMOKE_FAIL_NO_RETUNING"
SOURCE_COMMIT = "fa20f6d210fa8be7272178b1f152e38b2d583637"
SOURCE_URL = (
    "https://huggingface.co/datasets/Yesianrohn/OCR-Data/resolve/"
    "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c/"
    "data/openvino-00000-of-00001.parquet?download=true"
)
SOURCE_OBJECT_SHA256 = (
    "5413c6ffb4f8047977db9dba520453976f48eed91b5477d06e7f62258a2ba09c"
)
MODEL_ARTIFACT_ID = 8917522937
MODEL_ZIP_SHA256 = (
    "080b0efd4b91a180a1a5c6acd767d72e0a8f286718e64eb90d8ec9d370d2dc17"
)
MODEL_SHA256 = (
    "53229915331c2bbea2454f9e7cb5768a26e9edb30de750747f4397f1ff4cf92c"
)
MODEL_CANDIDATE_STABLE_SHA256 = (
    "0f88d94af81e0f7921e654e452059d2075b07ee35bcffd83dd8b02ebdd9e93a1"
)
POLICY_SOURCE_SHA256 = (
    "5b37aa3ac9f349e708624e815dab97e2ab1eaaac4a905499de15aa3513862b2d"
)
EXPECTED_SMOKE: tuple[tuple[int, str], ...] = (
    (80108, "298cadbae09ccedb"),
    (97623, "2f59c53adbcbebaf"),
    (132271, "5a92951f558f9576"),
    (89731, "2cb6b047b0a43daf"),
    (12504, "1c00e32279ef8678"),
    (127767, "59211f4813bc7ac7"),
    (191703, "099a638d78046e76"),
    (44625, "11e237f57418b2b2"),
    (91944, "2d730228a11fda4c"),
    (193955, "2afaedc20f715c25"),
    (74899, "27d31d0e3444b239"),
    (207373, "fa3d890c4d8eab8e"),
    (75546, "280838e7e4d6d776"),
    (52897, "20c1c8cccb1b3cfe"),
    (103733, "5148ba9f4eda9f13"),
    (135780, "5bbe4e23749c4f40"),
)
SOURCE_FILES = (
    "ocr_real_risk_v1/core.py",
    "ocr_real_risk_v1/exact_bounds.py",
    "ocr_real_risk_v1/isolated_crop.py",
    "ocr_real_risk_v1/pixel_digit_alignment.py",
    "ocr_real_risk_v1/sroie_natural_holdout.py",
    "ocr_real_risk_v1/numeric_digit_forest.py",
    "ocr_real_risk_v1/cord_source_seal.py",
    "ocr_real_risk_v1/numeric_digit_forest_deterministic.py",
    "ocr_real_risk_v1/cord_natural_holdout.py",
    "ocr_real_risk_v1/cord_consensus_detector_v4.py",
    "ocr_real_risk_v1/cord_detector_crops_v4.py",
    "ocr_real_risk_v1/textocr_adapter_v6.py",
    "ocr_real_risk_v1/numeric_consensus_policy_v7.py",
)
EXPECTED_RUNTIME = {
    "python_major_minor": "3.11",
    "tesseract": "5.3.4",
    "Pillow": "12.2.0",
    "numpy": "2.2.6",
    "opencv": "4.10.0",
    "scikit_learn": "1.8.0",
    "joblib": "1.5.3",
    "pyarrow": "18.1.0",
    "pytesseract": "0.3.13",
    "duckdb": "1.5.5",
}


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def verify_source_identity() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for relative in SOURCE_FILES:
        path = Path(relative)
        if not path.is_file():
            raise RuntimeError(f"missing frozen source file: {relative}")
        current_blob = _git("hash-object", relative)
        frozen_blob = _git("rev-parse", f"{SOURCE_COMMIT}:{relative}")
        if current_blob != frozen_blob:
            raise RuntimeError(f"frozen source drift: {relative}")
        records.append(
            {
                "path": relative,
                "git_blob_sha1": current_blob,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    policy_sha = sha256_file(Path("ocr_real_risk_v1/numeric_consensus_policy_v7.py"))
    if policy_sha != POLICY_SOURCE_SHA256:
        raise RuntimeError(f"frozen v7 policy SHA mismatch: {policy_sha}")
    return {
        "source_commit": SOURCE_COMMIT,
        "files": records,
        "policy_source_sha256": policy_sha,
        "all_match_frozen_commit": True,
    }


def runtime_identity() -> dict[str, Any]:
    version_text = subprocess.check_output(
        ["tesseract", "--version"], text=True, stderr=subprocess.STDOUT
    )
    first = version_text.splitlines()[0].strip()
    result = {
        "python": platform.python_version(),
        "tesseract_version_line": first,
        "packages": {
            "Pillow": PIL.__version__,
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
            "pyarrow": pyarrow.__version__,
            "pytesseract": pytesseract.__version__,
            "duckdb": duckdb.__version__,
        },
        "expected": EXPECTED_RUNTIME,
    }
    result["strict_match"] = bool(
        platform.python_version().startswith("3.11.")
        and first.lower().startswith("tesseract 5.3.4")
        and PIL.__version__ == "12.2.0"
        and np.__version__ == "2.2.6"
        and cv2.__version__.startswith("4.10.0")
        and sklearn.__version__ == "1.8.0"
        and joblib.__version__ == "1.5.3"
        and pyarrow.__version__ == "18.1.0"
        and pytesseract.__version__ == "0.3.13"
        and duckdb.__version__ == "1.5.5"
    )
    if not result["strict_match"]:
        raise RuntimeError("FROZEN_RUNTIME_MISMATCH")
    return result


def load_model(model_zip: Path, root: Path) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    if sha256_file(model_zip) != MODEL_ZIP_SHA256:
        raise RuntimeError("model artifact ZIP SHA mismatch")
    with zipfile.ZipFile(model_zip) as archive:
        names = archive.namelist()
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise RuntimeError("unsafe model ZIP member")
        archive.extractall(root)
    candidates = list(root.rglob("frozen_candidate.json"))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one frozen_candidate.json, found {len(candidates)}")
    model_root = candidates[0].parent
    candidate, model = load_frozen_candidate(model_root)
    model_path = model_root / "digit_forest.joblib"
    if sha256_file(model_path) != MODEL_SHA256:
        raise RuntimeError("model file SHA mismatch")
    if candidate.get("candidate_id") != "digit-forest-v3":
        raise RuntimeError("unexpected model candidate ID")
    if candidate.get("stable_payload_sha256") != MODEL_CANDIDATE_STABLE_SHA256:
        raise RuntimeError("model candidate stable payload mismatch")
    if float(candidate["inference"]["threshold"]) != FOREST_MINIMUM_MEAN_PROBABILITY:
        raise RuntimeError("model/policy threshold mismatch")
    if len(model.estimators_) != 500:
        raise RuntimeError("model tree count mismatch")
    return candidate, model, {
        "artifact_id": MODEL_ARTIFACT_ID,
        "zip_sha256": MODEL_ZIP_SHA256,
        "model_sha256": MODEL_SHA256,
        "candidate_stable_payload_sha256": MODEL_CANDIDATE_STABLE_SHA256,
        "model_root": str(model_root),
        "tree_count": len(model.estimators_),
    }


def _source_sql() -> str:
    return "'" + SOURCE_URL.replace("'", "''") + "'"


def _row_in_list() -> str:
    return ",".join(str(row_index) for row_index, _ in EXPECTED_SMOKE)


def fetch_images(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    sql = (
        "SELECT file_row_number::BIGINT AS row_index, "
        "image.path::VARCHAR AS image_path, image.bytes AS image_bytes "
        f"FROM read_parquet({_source_sql()}, file_row_number=true) "
        f"WHERE file_row_number IN ({_row_in_list()}) "
        "ORDER BY file_row_number"
    )
    rows = connection.execute(sql).fetchall()
    expected = dict(EXPECTED_SMOKE)
    if len(rows) != len(EXPECTED_SMOKE):
        raise RuntimeError(f"image query returned {len(rows)} rows, expected 16")
    result: list[dict[str, Any]] = []
    for raw_index, raw_path, raw_bytes in rows:
        row_index = int(raw_index)
        image_path = str(raw_path or "")
        image_id = image_path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        if expected.get(row_index) != image_id:
            raise RuntimeError(
                f"smoke row/ImageID drift: {row_index}/{image_id}/"
                f"{expected.get(row_index)}"
            )
        image_bytes = bytes(raw_bytes)
        if not image_bytes:
            raise RuntimeError(f"empty image bytes: {row_index}")
        result.append(
            {
                "row_index": row_index,
                "image_id": image_id,
                "image_path": image_path,
                "image_bytes": image_bytes,
                "encoded_bytes": len(image_bytes),
                "encoded_sha256": sha256_bytes(image_bytes),
            }
        )
    if {(row["row_index"], row["image_id"]) for row in result} != set(EXPECTED_SMOKE):
        raise RuntimeError("smoke pair set mismatch")
    return result


def run_outcome_blind_detector(images: Sequence[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    outputs: dict[int, dict[str, Any]] = {}
    for ordinal, record in enumerate(images, start=1):
        with Image.open(io.BytesIO(record["image_bytes"])) as opened:
            image = opened.convert("RGB")
        started = time.perf_counter()
        raw_candidates: list[dict[str, Any]] = []
        psm_runtime: dict[str, Any] = {}
        for psm in PSM_MODES:
            candidates, runtime = tesseract_numeric_candidates(image, int(psm))
            raw_candidates.extend(candidates)
            psm_runtime[str(psm)] = runtime
        clusters = cluster_candidates(raw_candidates)
        tokens = resolved_tokens(clusters, SELECTED_CONFIGURATION)
        detector_seconds = time.perf_counter() - started
        outputs[int(record["row_index"])] = {
            "row_index": int(record["row_index"]),
            "image_id": str(record["image_id"]),
            "encoded_sha256": str(record["encoded_sha256"]),
            "image_size": [image.width, image.height],
            "mode": image.mode,
            "decode_ok": True,
            "raw_candidates": len(raw_candidates),
            "clusters": len(clusters),
            "resolved_tokens": tokens,
            "psm_runtime": psm_runtime,
            "detector_wall_seconds": detector_seconds,
            "all_psm_calls_terminal": all(
                not bool(runtime.get("timeout")) for runtime in psm_runtime.values()
            ),
        }
        print(
            json.dumps(
                {
                    "phase": "outcome_blind_inference",
                    "ordinal": ordinal,
                    "rows": len(images),
                    "row_index": record["row_index"],
                    "image_id": record["image_id"],
                    "tokens": len(tokens),
                    "seconds": detector_seconds,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if len(outputs) != len(EXPECTED_SMOKE):
        raise RuntimeError("outcome-blind inference did not complete all rows")
    return outputs


def fetch_annotations(
    connection: duckdb.DuckDBPyConnection,
) -> dict[int, tuple[Any, Any, Any, Any]]:
    sql = (
        "SELECT file_row_number::BIGINT AS row_index, "
        "texts, bboxes, polygons, num_text_regions "
        f"FROM read_parquet({_source_sql()}, file_row_number=true) "
        f"WHERE file_row_number IN ({_row_in_list()}) "
        "ORDER BY file_row_number"
    )
    rows = connection.execute(sql).fetchall()
    if len(rows) != len(EXPECTED_SMOKE):
        raise RuntimeError(f"annotation query returned {len(rows)} rows")
    return {
        int(row_index): (texts, bboxes, polygons, num_regions)
        for row_index, texts, bboxes, polygons, num_regions in rows
    }


def score_after_quarantine(
    images: Sequence[dict[str, Any]],
    inference: Mapping[int, Mapping[str, Any]],
    annotations: Mapping[int, tuple[Any, Any, Any, Any]],
    model: Any,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for ordinal, record in enumerate(images, start=1):
        row_index = int(record["row_index"])
        texts, bboxes, polygons, num_regions = annotations[row_index]
        selected, selection_counts = select_numeric_annotation(
            row_index=row_index,
            texts=texts,
            bboxes=bboxes,
            polygons=polygons,
            num_text_regions=num_regions,
        )
        if selected is None:
            raise RuntimeError(f"frozen smoke row lost selected annotation: {row_index}")
        with Image.open(io.BytesIO(record["image_bytes"])) as opened:
            image = opened.convert("RGB")
        detector = dict(inference[row_index])
        tokens = detector["resolved_tokens"]
        matched = match_ocr_claim(selected["bbox_xyxy"], tokens)
        claim, eligible, eligibility_reason = inference_eligibility(matched)
        forest: dict[str, Any] | None = None
        guard: dict[str, Any] | None = None
        candidate_output: str | None = None
        candidate_seconds = 0.0
        crop_coordinates: list[int] | None = None
        if eligible and matched is not None:
            box = crop_box(image, matched["bbox"], margin=2)
            crop_coordinates = list(box)
            crop = image.crop(box)
            started = time.perf_counter()
            forest = infer_claim(
                model,
                crop,
                claim,
                threshold=FOREST_MINIMUM_MEAN_PROBABILITY,
            )
            guard = crop_guard_readings(crop)
            candidate_row = {
                "candidate": {
                    "claim": claim,
                    "prediction": forest.get("prediction"),
                    "minimum_mean_probability": forest.get(
                        "minimum_mean_probability"
                    ),
                    "guard": guard,
                    "matched": matched,
                }
            }
            candidate_output = predict_v7_claim_verifier(candidate_row)
            candidate_seconds = time.perf_counter() - started
        truth = str(selected["truth"])
        baseline_output = claim if eligible else None
        row_result = {
            "row_index": row_index,
            "image_id": record["image_id"],
            "encoded_bytes": record["encoded_bytes"],
            "encoded_sha256": record["encoded_sha256"],
            "image_size": detector["image_size"],
            "decode_ok": detector["decode_ok"],
            "geometry_ok": True,
            "selection_rank_sha256": selected["selection_rank_sha256"],
            "annotation_index": selected["annotation_index"],
            "bbox_xyxy": selected["bbox_xyxy"],
            "bbox_convention": selected["bbox_convention"],
            "bbox_polygon_iou": selected["bbox_polygon_iou"],
            "selection_counts": selection_counts,
            "truth": truth,
            "detector": {
                "raw_candidates": detector["raw_candidates"],
                "clusters": detector["clusters"],
                "resolved_tokens": len(tokens),
                "wall_seconds": detector["detector_wall_seconds"],
                "psm_runtime": detector["psm_runtime"],
                "all_psm_calls_terminal": detector["all_psm_calls_terminal"],
            },
            "match": matched,
            "claim": claim,
            "eligible": eligible,
            "eligibility_reason": eligibility_reason,
            "baseline_output": baseline_output,
            "baseline_correct": (
                baseline_output == truth if baseline_output is not None else None
            ),
            "crop_box": crop_coordinates,
            "forest": forest,
            "guard": guard,
            "candidate_output": candidate_output,
            "candidate_accepted": candidate_output is not None,
            "candidate_correct": (
                candidate_output == truth if candidate_output is not None else None
            ),
            "candidate_wall_seconds": candidate_seconds,
            "equal_length_conflicts": (
                list(matched.get("equal_length_conflicts") or [])
                if isinstance(matched, Mapping)
                else []
            ),
            "terminal": True,
        }
        results.append(row_result)
        print(
            json.dumps(
                {
                    "phase": "post_inference_scoring",
                    "ordinal": ordinal,
                    "rows": len(images),
                    "row_index": row_index,
                    "eligible": eligible,
                    "candidate_accepted": candidate_output is not None,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return results


def build_receipt(
    *,
    source_identity: Mapping[str, Any],
    runtime: Mapping[str, Any],
    model_identity: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    started: float,
) -> dict[str, Any]:
    all_terminal = len(rows) == 16 and all(bool(row["terminal"]) for row in rows)
    all_decode = all(bool(row["decode_ok"]) for row in rows)
    all_geometry = all(bool(row["geometry_ok"]) for row in rows)
    no_psm_timeout = all(
        bool(row["detector"]["all_psm_calls_terminal"]) for row in rows
    )
    guard_timeouts = sum(
        int(bool(reading.get("timeout")))
        for row in rows
        for reading in (
            (row.get("guard") or {}).get("readings", {}).values()
            if isinstance(row.get("guard"), Mapping)
            else []
        )
    )
    smoke_pass = bool(
        all_terminal
        and all_decode
        and all_geometry
        and no_psm_timeout
        and guard_timeouts == 0
    )
    detector_seconds = sum(float(row["detector"]["wall_seconds"]) for row in rows)
    candidate_seconds = sum(float(row["candidate_wall_seconds"]) for row in rows)
    baseline_eligible = sum(bool(row["eligible"]) for row in rows)
    candidate_accepted = sum(bool(row["candidate_accepted"]) for row in rows)
    baseline_errors = sum(row["baseline_correct"] is False for row in rows)
    candidate_errors = sum(row["candidate_correct"] is False for row in rows)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS_PASS if smoke_pass else STATUS_FAIL,
        "engineering_only": True,
        "scientific_verdict": False,
        "scale_up_authorized": False,
        "retuning_authorized": False,
        "source": {
            "dataset": "Yesianrohn/OCR-Data",
            "component": "openvino",
            "revision": "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c",
            "object_sha256": SOURCE_OBJECT_SHA256,
            "smoke_pairs": [
                {"row_index": row_index, "image_id": image_id}
                for row_index, image_id in EXPECTED_SMOKE
            ],
            "opened_image_rows": 16,
            "opened_encoded_bytes": sum(int(row["encoded_bytes"]) for row in rows),
            "annotation_query_executed_after_all_inference": True,
        },
        "source_identity": source_identity,
        "runtime": runtime,
        "model": model_identity,
        "policy": policy_manifest(),
        "execution": {
            "rows_expected": 16,
            "rows_terminal": len(rows),
            "all_terminal": all_terminal,
            "all_decode_ok": all_decode,
            "all_geometry_ok": all_geometry,
            "no_psm_timeout": no_psm_timeout,
            "guard_timeout_count": guard_timeouts,
            "baseline_eligible": baseline_eligible,
            "candidate_accepted": candidate_accepted,
            "baseline_errors_on_eligible": baseline_errors,
            "candidate_errors_on_accepted": candidate_errors,
            "detector_wall_seconds_sum": detector_seconds,
            "candidate_verifier_wall_seconds_sum": candidate_seconds,
            "candidate_to_detector_time_ratio": (
                candidate_seconds / detector_seconds if detector_seconds else None
            ),
            "total_wall_seconds": time.perf_counter() - started,
            "quality_or_speed_claimed": False,
        },
        "rows": list(rows),
        "next_gate": (
            "SEPARATE_COST_GATE_BEFORE_20613_ROW_FULL_EXECUTION"
            if smoke_pass
            else "STOP_NO_RETUNING_REPORT_FAILURE"
        ),
        "constraints": {
            "images_opened": 16,
            "full_scientific_rows_opened": 0,
            "gpu_used": False,
            "paid_ocr_api_used": False,
            "production_modified": False,
            "external_spend_usd": 0,
        },
    }
    receipt["receipt_sha256"] = sha256_bytes(_canonical_bytes(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    source_identity = verify_source_identity()
    runtime = runtime_identity()
    with tempfile.TemporaryDirectory(prefix="openvino-v7-model-") as temporary:
        candidate, model, model_identity = load_model(
            args.model_zip, Path(temporary)
        )
        connection = duckdb.connect(database=":memory:")
        connection.execute("SET threads=1")
        connection.execute("SET preserve_insertion_order=true")
        images = fetch_images(connection)
        inference = run_outcome_blind_detector(images)
        annotations = fetch_annotations(connection)
        rows = score_after_quarantine(images, inference, annotations, model)
    receipt = build_receipt(
        source_identity=source_identity,
        runtime=runtime,
        model_identity=model_identity,
        rows=rows,
        started=started,
    )
    receipt_path = args.output_dir / "openvino_v7_smoke_receipt.json"
    receipt_path.write_bytes(_canonical_bytes(receipt))
    rows_path = args.output_dir / "openvino_v7_smoke_rows.jsonl"
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    (args.output_dir / "SHA256SUMS.txt").write_text(
        f"{sha256_file(receipt_path)}  {receipt_path.name}\n"
        f"{sha256_file(rows_path)}  {rows_path.name}\n",
        encoding="utf-8",
    )
    print("@@OPENVINO_V7_SMOKE@@" + json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == STATUS_PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
