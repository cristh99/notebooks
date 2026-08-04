"""Independent full-page numeric verifier hidden behind Tesseract concurrency.

The primary OCR result is Tesseract. In parallel, an independent PP-OCRv6 tiny
pipeline performs its own 1024-pixel full-page detection and recognition. The
accepted numeric evidence channel is the repeated-token intersection of both
full-page outputs. No boxes, crops, or segmentations are shared.

Logic Power is a development-time planner only and is absent from this runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image
import pytesseract

from ocr_god_10x_quality_v1.full_content_quality import (
    canonical_json,
    number_tokens,
    normalize_text,
    sha256_bytes,
    sha256_file,
)
from ocr_numeric_proof_10x_v1.policy import (
    MIN_ACCEPTED,
    MIN_ERROR_REDUCTION,
    MIN_LOO_PASSES,
    MIN_PRECISION,
    MIN_REFERENCE_COVERAGE,
    accepted_counter,
    multiset_metrics,
)

SCHEMA = "ocr-numeric-parallel-10x/benchmark/1"
DATASET_ID = "opendatalab/OmniDocBench"
DATASET_REVISION = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"
ANNOTATION_SHA256 = "a45cd84b04ad8b793e775089640e6b681209abea33ead54c1828ddca35fae496"
PP_LIMIT = 1024
THREAD_BUDGET = 10
MAX_PAIR_RATIO = 1.12
MAX_MEAN_EXTRA_SECONDS = 0.30
MAX_P90_EXTRA_SECONDS = 0.60
MIN_FROZEN_PARITY_F1 = 0.999
LOO_MIN_ACCEPTED = 250


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cpu_self() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def _cpu_children() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(usage.ru_utime + usage.ru_stime)


def _unwrap(result: Any) -> Mapping[str, Any]:
    payload = result.json
    if callable(payload):
        payload = payload()
    if not isinstance(payload, Mapping):
        raise TypeError(f"unexpected Paddle result payload: {type(payload)!r}")
    inner = payload.get("res", payload)
    if not isinstance(inner, Mapping):
        raise TypeError("Paddle result does not contain a mapping")
    return inner


def make_pipeline() -> tuple[Any, dict[str, float]]:
    from paddleocr import PaddleOCR

    started = time.perf_counter()
    pipeline = PaddleOCR(
        text_detection_model_name="PP-OCRv6_tiny_det",
        text_recognition_model_name="PP-OCRv6_tiny_rec",
        device="cpu",
        enable_hpi=True,
        cpu_threads=THREAD_BUDGET,
        text_recognition_batch_size=32,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    initialized = time.perf_counter()
    blank = np.full((256, 1024, 3), 255, dtype=np.uint8)
    list(
        pipeline.predict(
            blank,
            text_det_limit_side_len=PP_LIMIT,
            text_det_limit_type="max",
        )
    )
    warmed = time.perf_counter()
    return pipeline, {
        "model_initialization_seconds": initialized - started,
        "warmup_seconds": warmed - initialized,
    }


def run_tesseract(image: Image.Image) -> tuple[str, dict[str, float]]:
    os.environ["OMP_THREAD_LIMIT"] = str(THREAD_BUDGET)
    before_cpu = _cpu_children()
    started = time.perf_counter()
    output = pytesseract.image_to_string(
        image,
        lang="eng",
        config="--oem 1 --psm 3",
    )
    wall = time.perf_counter() - started
    cpu = max(0.0, _cpu_children() - before_cpu)
    return normalize_text(output), {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
    }


def run_pp(
    pipeline: Any,
    image_array: np.ndarray,
) -> tuple[str, dict[str, Any]]:
    before_cpu = _cpu_self()
    started = time.perf_counter()
    results = list(
        pipeline.predict(
            image_array,
            text_det_limit_side_len=PP_LIMIT,
            text_det_limit_type="max",
        )
    )
    wall = time.perf_counter() - started
    cpu = max(0.0, _cpu_self() - before_cpu)
    if len(results) != 1:
        raise RuntimeError(f"expected one Paddle result, observed {len(results)}")
    payload = _unwrap(results[0])
    texts = [normalize_text(str(value)) for value in payload.get("rec_texts", [])]
    scores = [float(value) for value in payload.get("rec_scores", [])]
    boxes = [[int(value) for value in row] for row in payload.get("rec_boxes", [])]
    if len(texts) != len(scores) or len(texts) != len(boxes):
        raise RuntimeError("Paddle text, score and box denominators differ")
    output = "\n".join(text for text in texts if text)
    return output, {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "line_count": len(texts),
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "prediction_sha256": _sha256_text(output),
    }


def run_parallel_pair(
    executor: ThreadPoolExecutor,
    pipeline: Any,
    image: Image.Image,
    image_array: np.ndarray,
) -> dict[str, Any]:
    started = time.perf_counter()
    tesseract_future = executor.submit(run_tesseract, image)
    pp_text, pp_runtime = run_pp(pipeline, image_array)
    tesseract_text, tesseract_runtime = tesseract_future.result()
    pair_wall = time.perf_counter() - started
    return {
        "pair_wall_seconds": pair_wall,
        "tesseract": {
            "text": tesseract_text,
            "runtime": tesseract_runtime,
            "prediction_sha256": _sha256_text(tesseract_text),
        },
        "pp_1024": {
            "text": pp_text,
            "runtime": pp_runtime,
            "prediction_sha256": _sha256_text(pp_text),
        },
    }


def counter_parity(
    observed: Counter[str],
    reference: Counter[str],
) -> dict[str, Any]:
    metrics = multiset_metrics(reference, observed)
    return {
        "f1": metrics["f1"],
        "precision": metrics["precision"],
        "reference_coverage": metrics["reference_coverage"],
        "matching_count": metrics["true_positive"],
        "observed_count": metrics["prediction_count"],
        "reference_count": metrics["reference_count"],
    }


def evaluate_pages(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reference: Counter[str] = Counter()
    baseline: Counter[str] = Counter()
    accepted: Counter[str] = Counter()
    for page in pages:
        reference.update(str(value) for value in page["reference_tokens"])
        baseline.update(str(value) for value in page["tesseract_tokens"])
        accepted.update(str(value) for value in page["accepted_tokens"])
    baseline_metrics = multiset_metrics(reference, baseline)
    policy_metrics = multiset_metrics(reference, accepted)
    baseline_error = float(baseline_metrics["false_acceptance_rate"])
    policy_error = float(policy_metrics["false_acceptance_rate"])
    reduction = baseline_error / policy_error if policy_error > 1e-15 else None
    return {
        "pages": len(pages),
        "baseline": baseline_metrics,
        "policy": policy_metrics,
        "false_acceptance_error_reduction_factor": reduction,
    }


def loo_diagnostics(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for index, held_out in enumerate(pages):
        subset = [page for offset, page in enumerate(pages) if offset != index]
        evaluation = evaluate_pages(subset)
        policy = evaluation["policy"]
        reduction = evaluation["false_acceptance_error_reduction_factor"]
        passes = bool(
            (reduction is None or float(reduction) >= MIN_ERROR_REDUCTION)
            and float(policy["precision"]) >= MIN_PRECISION
            and float(policy["reference_coverage"]) >= MIN_REFERENCE_COVERAGE
            and int(policy["prediction_count"]) >= LOO_MIN_ACCEPTED
        )
        folds.append(
            {
                "held_out_page_id": held_out["page_id"],
                "passes": passes,
                "precision": policy["precision"],
                "reference_coverage": policy["reference_coverage"],
                "accepted_count": policy["prediction_count"],
                "error_reduction_factor": reduction,
            }
        )
    finite = [
        float(fold["error_reduction_factor"])
        for fold in folds
        if fold["error_reduction_factor"] is not None
    ]
    return {
        "folds": folds,
        "passes": sum(bool(fold["passes"]) for fold in folds),
        "fold_count": len(folds),
        "minimum_error_reduction_factor": min(finite) if finite else None,
        "maximum_error_reduction_factor": max(finite) if finite else None,
    }


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must lie in [0, 1]")
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[index]


def runtime_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    isolated_tesseract = sum(
        float(row["isolated"]["tesseract"]["runtime"]["wall_seconds"])
        for row in rows
    )
    isolated_pp = sum(
        float(row["isolated"]["pp_1024"]["runtime"]["wall_seconds"])
        for row in rows
    )
    pair_wall = sum(float(row["parallel"]["pair_wall_seconds"]) for row in rows)
    extras = [
        float(row["parallel"]["pair_wall_seconds"])
        - float(row["isolated"]["tesseract"]["runtime"]["wall_seconds"])
        for row in rows
    ]
    page_count = max(len(rows), 1)
    raw_ratio = pair_wall / max(isolated_tesseract, 1e-15)
    extra_total = pair_wall - isolated_tesseract
    hidden_fraction = 1.0 - max(extra_total, 0.0) / max(isolated_pp, 1e-15)
    return {
        "pages": len(rows),
        "isolated_tesseract_total_wall_seconds": isolated_tesseract,
        "isolated_tesseract_mean_wall_seconds_per_page": isolated_tesseract / page_count,
        "isolated_pp_1024_total_wall_seconds": isolated_pp,
        "isolated_pp_1024_mean_wall_seconds_per_page": isolated_pp / page_count,
        "sequential_total_wall_seconds": isolated_tesseract + isolated_pp,
        "parallel_pair_total_wall_seconds": pair_wall,
        "parallel_pair_mean_wall_seconds_per_page": pair_wall / page_count,
        "pair_ratio_to_tesseract": raw_ratio,
        "pair_overhead_fraction": raw_ratio - 1.0,
        "extra_wall_seconds_total": extra_total,
        "mean_extra_wall_seconds_per_page": extra_total / page_count,
        "p90_page_extra_wall_seconds": percentile(extras, 0.90),
        "maximum_page_extra_wall_seconds": max(extras) if extras else 0.0,
        "parallel_speedup_vs_sequential": (
            (isolated_tesseract + isolated_pp) / max(pair_wall, 1e-15)
        ),
        "pp_wall_fraction_hidden": hidden_fraction,
        "page_extra_wall_seconds": extras,
    }


def stable_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"environment", "stable_payload_sha256"}
    }


def _accepted_list(counter: Counter[str]) -> list[str]:
    return [
        token
        for token in sorted(counter)
        for _ in range(counter[token])
    ]


def _load_speed_pages(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = report.get("observations") or []
    return {str(row["page_id"]): row for row in rows}


def build_report(
    quality_report_path: Path,
    speed_frontier_report_path: Path,
    quality_artifact_sha256: str,
    speed_artifact_sha256: str,
) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download

    quality = json.loads(quality_report_path.read_text(encoding="utf-8"))
    speed = json.loads(speed_frontier_report_path.read_text(encoding="utf-8"))
    quality_rows = quality.get("observations") or []
    if len(quality_rows) != 20:
        raise RuntimeError(f"expected 20 quality pages, observed {len(quality_rows)}")
    page_ids = [str(row["page_id"]) for row in quality_rows]
    if len(set(page_ids)) != len(page_ids):
        raise RuntimeError("duplicate quality page identities")
    speed_by_page = _load_speed_pages(speed)
    if set(speed_by_page) != set(page_ids):
        raise RuntimeError("speed-frontier and quality page sets differ")

    annotation_path = Path(
        hf_hub_download(
            DATASET_ID,
            "OmniDocBench.json",
            repo_type="dataset",
            revision=DATASET_REVISION,
        )
    )
    if sha256_file(annotation_path) != ANNOTATION_SHA256:
        raise RuntimeError("annotation hash mismatch")

    images: dict[str, Image.Image] = {}
    arrays: dict[str, np.ndarray] = {}
    image_manifest: list[dict[str, Any]] = []
    for page_id in page_ids:
        dataset_path = page_id if page_id.startswith("images/") else f"images/{page_id}"
        image_path = Path(
            hf_hub_download(
                DATASET_ID,
                dataset_path,
                repo_type="dataset",
                revision=DATASET_REVISION,
            )
        )
        image = Image.open(image_path).convert("RGB")
        images[page_id] = image
        arrays[page_id] = np.asarray(image)
        image_manifest.append(
            {
                "page_id": page_id,
                "dataset_path": dataset_path,
                "sha256": sha256_file(image_path),
                "bytes": image_path.stat().st_size,
                "width": image.width,
                "height": image.height,
            }
        )

    pipeline, initialization = make_pipeline()
    quality_by_page = {str(row["page_id"]): row for row in quality_rows}
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tesseract") as executor:
        executor.submit(lambda: None).result()
        for index, page_id in enumerate(page_ids):
            image = images[page_id]
            image_array = arrays[page_id]

            if index % 2 == 0:
                t_text, t_runtime = run_tesseract(image)
                p_text, p_runtime = run_pp(pipeline, image_array)
                parallel = run_parallel_pair(
                    executor,
                    pipeline,
                    image,
                    image_array,
                )
                order = "isolated_then_parallel"
            else:
                parallel = run_parallel_pair(
                    executor,
                    pipeline,
                    image,
                    image_array,
                )
                p_text, p_runtime = run_pp(pipeline, image_array)
                t_text, t_runtime = run_tesseract(image)
                order = "parallel_then_isolated"

            isolated = {
                "tesseract": {
                    "text": t_text,
                    "runtime": t_runtime,
                    "prediction_sha256": _sha256_text(t_text),
                },
                "pp_1024": {
                    "text": p_text,
                    "runtime": p_runtime,
                    "prediction_sha256": _sha256_text(p_text),
                },
            }
            if (
                isolated["tesseract"]["prediction_sha256"]
                != parallel["tesseract"]["prediction_sha256"]
            ):
                raise RuntimeError(f"Tesseract output changed under concurrency: {page_id}")
            if (
                isolated["pp_1024"]["prediction_sha256"]
                != parallel["pp_1024"]["prediction_sha256"]
            ):
                raise RuntimeError(f"PP output changed under concurrency: {page_id}")

            quality_row = quality_by_page[page_id]
            reference_tokens = number_tokens(str(quality_row["reference"]["full"]))
            tesseract_tokens = number_tokens(parallel["tesseract"]["text"])
            pp_tokens = number_tokens(parallel["pp_1024"]["text"])
            accepted = accepted_counter(
                Counter(tesseract_tokens),
                Counter(pp_tokens),
            )

            frozen_row = speed_by_page[page_id]
            frozen_tesseract_tokens = number_tokens(
                str(frozen_row["engines"]["tesseract"]["text"])
            )
            frozen_pp_tokens = number_tokens(
                str(frozen_row["engines"]["max_1024"]["text"])
            )
            rows.append(
                {
                    "page_id": page_id,
                    "crossover_order": order,
                    "reference_tokens": reference_tokens,
                    "tesseract_tokens": tesseract_tokens,
                    "pp_1024_tokens": pp_tokens,
                    "accepted_tokens": _accepted_list(accepted),
                    "frozen_tesseract_tokens": frozen_tesseract_tokens,
                    "frozen_pp_1024_tokens": frozen_pp_tokens,
                    "isolated": isolated,
                    "parallel": parallel,
                }
            )

    evaluation = evaluate_pages(rows)
    loo = loo_diagnostics(rows)
    runtime = runtime_metrics(rows)

    actual_tesseract: Counter[str] = Counter()
    actual_pp: Counter[str] = Counter()
    frozen_tesseract: Counter[str] = Counter()
    frozen_pp: Counter[str] = Counter()
    for row in rows:
        actual_tesseract.update(str(value) for value in row["tesseract_tokens"])
        actual_pp.update(str(value) for value in row["pp_1024_tokens"])
        frozen_tesseract.update(str(value) for value in row["frozen_tesseract_tokens"])
        frozen_pp.update(str(value) for value in row["frozen_pp_1024_tokens"])
    parity = {
        "tesseract_vs_frozen_speed_frontier": counter_parity(
            actual_tesseract,
            frozen_tesseract,
        ),
        "pp_1024_vs_frozen_speed_frontier": counter_parity(
            actual_pp,
            frozen_pp,
        ),
        "isolated_parallel_text_hashes_equal": all(
            row["isolated"]["tesseract"]["prediction_sha256"]
            == row["parallel"]["tesseract"]["prediction_sha256"]
            and row["isolated"]["pp_1024"]["prediction_sha256"]
            == row["parallel"]["pp_1024"]["prediction_sha256"]
            for row in rows
        ),
    }

    policy = evaluation["policy"]
    reduction = evaluation["false_acceptance_error_reduction_factor"]
    quality_gate = bool(
        (reduction is None or float(reduction) >= MIN_ERROR_REDUCTION)
        and float(policy["precision"]) >= MIN_PRECISION
        and float(policy["reference_coverage"]) >= MIN_REFERENCE_COVERAGE
        and int(policy["prediction_count"]) >= MIN_ACCEPTED
        and int(loo["passes"]) >= MIN_LOO_PASSES
    )
    parity_gate = bool(
        parity["isolated_parallel_text_hashes_equal"]
        and float(parity["tesseract_vs_frozen_speed_frontier"]["f1"])
        >= MIN_FROZEN_PARITY_F1
        and float(parity["pp_1024_vs_frozen_speed_frontier"]["f1"])
        >= MIN_FROZEN_PARITY_F1
    )
    runtime_gate = bool(
        float(runtime["pair_ratio_to_tesseract"]) <= MAX_PAIR_RATIO
        and float(runtime["mean_extra_wall_seconds_per_page"])
        <= MAX_MEAN_EXTRA_SECONDS
        and float(runtime["p90_page_extra_wall_seconds"])
        <= MAX_P90_EXTRA_SECONDS
        and parity_gate
    )
    promotion_gate = quality_gate and runtime_gate
    verdict = (
        "PASS_PARALLEL_NUMERIC_PROOF_10X"
        if promotion_gate
        else (
            "QUALITY_PASS_PARALLEL_RUNTIME_FAILED"
            if quality_gate
            else "PARALLEL_NUMERIC_PROOF_QUALITY_FAILED"
        )
    )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "quality_report_sha256": sha256_file(quality_report_path),
            "quality_stable_payload_sha256": quality["stable_payload_sha256"],
            "quality_artifact_sha256": quality_artifact_sha256,
            "speed_frontier_report_sha256": sha256_file(
                speed_frontier_report_path
            ),
            "speed_frontier_stable_payload_sha256": speed[
                "stable_payload_sha256"
            ],
            "speed_artifact_sha256": speed_artifact_sha256,
            "dataset_id": DATASET_ID,
            "dataset_revision": DATASET_REVISION,
            "annotation_sha256": ANNOTATION_SHA256,
        },
        "runtime_contract": {
            "primary_engine": "Tesseract",
            "independent_verifier": "PP-OCRv6_tiny_det + PP-OCRv6_tiny_rec",
            "pp_text_detection_limit_side_len": PP_LIMIT,
            "pp_text_detection_limit_type": "max",
            "shared_boxes": False,
            "shared_crops": False,
            "shared_segmentation": False,
            "execution": "concurrent on the same raster page",
            "thread_budget_per_engine": THREAD_BUDGET,
            "crossover_timing_design": True,
            "output_cache_reuse": False,
            "acceptance": (
                "per-page repeated canonical numeric intersection of two "
                "independent full-page OCR outputs"
            ),
            "all_other_numbers": "ABSTAIN_FROM_EVIDENCE_PROMOTION",
        },
        "gates": {
            "minimum_false_acceptance_error_reduction": MIN_ERROR_REDUCTION,
            "minimum_precision": MIN_PRECISION,
            "minimum_reference_coverage": MIN_REFERENCE_COVERAGE,
            "minimum_accepted_count": MIN_ACCEPTED,
            "minimum_leave_one_page_out_passes": MIN_LOO_PASSES,
            "minimum_frozen_parity_f1": MIN_FROZEN_PARITY_F1,
            "maximum_pair_ratio_to_tesseract": MAX_PAIR_RATIO,
            "maximum_mean_extra_seconds_per_page": MAX_MEAN_EXTRA_SECONDS,
            "maximum_p90_extra_seconds": MAX_P90_EXTRA_SECONDS,
        },
        "image_manifest": image_manifest,
        "pages": rows,
        "evaluation": evaluation,
        "leave_one_page_out": loo,
        "parity": parity,
        "runtime": runtime,
        "decision": {
            "verdict": verdict,
            "quality_gate": quality_gate,
            "parity_gate": parity_gate,
            "runtime_gate": runtime_gate,
            "promotion_gate": promotion_gate,
            "automatic_production_change": False,
            "next_experiment": (
                "open an untouched Honduran numeric holdout"
                if promotion_gate
                else "inspect the failed frozen gate without retuning quality"
            ),
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "logic_power_in_runtime": False,
            "native_text_counted_as_raster_speed": False,
            "dedup_cache_counted_as_raster_speed": False,
            "repeated_page_result_cache_used": False,
        },
        "initialization_excluded_from_steady_state": initialization,
    }
    payload["stable_payload_sha256"] = sha256_bytes(
        canonical_json(stable_payload(payload)).encode("utf-8")
    )
    payload["environment"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "tesseract": subprocess.check_output(
            ["tesseract", "--version"],
            text=True,
            stderr=subprocess.STDOUT,
        ).splitlines()[0],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--speed-frontier-report", type=Path, required=True)
    parser.add_argument("--quality-artifact-sha256", required=True)
    parser.add_argument("--speed-artifact-sha256", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_numeric_parallel_10x_v1/run"),
    )
    args = parser.parse_args()
    report = build_report(
        args.quality_report,
        args.speed_frontier_report,
        args.quality_artifact_sha256,
        args.speed_artifact_sha256,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "parallel_numeric_benchmark.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "parallel_numeric_benchmark.sha256").write_text(
        f"{sha256_file(path)}  parallel_numeric_benchmark.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(path),
                "evaluation": report["evaluation"],
                "leave_one_page_out": report["leave_one_page_out"],
                "parity": report["parity"],
                "runtime": report["runtime"],
                "decision": report["decision"],
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
