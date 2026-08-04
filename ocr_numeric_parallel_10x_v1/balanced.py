"""Asymmetric independent numeric verifier: Tesseract keeps priority, PP uses one thread.

This module reuses the already-verified independent full-page benchmark machinery,
but changes only resource allocation. Tesseract remains the primary OCR with its
ten-thread ceiling. The PP-OCR verifier is constrained to one CPU thread so the
combined steady-state demand fits the four-logical-CPU runner.

Logic Power remains a development-time planner and is absent from runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image
import pytesseract

from ocr_god_10x_quality_v1.full_content_quality import (
    canonical_json,
    sha256_bytes,
    sha256_file,
)
from ocr_numeric_proof_10x_v1.policy import (
    MIN_ACCEPTED,
    MIN_ERROR_REDUCTION,
    MIN_LOO_PASSES,
    MIN_PRECISION,
    MIN_REFERENCE_COVERAGE,
)

from . import benchmark as base

SCHEMA = "ocr-numeric-parallel-balanced-10x/benchmark/1"
TESSERACT_THREAD_BUDGET = 10
PP_THREAD_BUDGET = 1


def _cpu_children() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(usage.ru_utime + usage.ru_stime)


def make_balanced_pipeline() -> tuple[Any, dict[str, float]]:
    """Create the same frozen verifier models with a one-thread CPU budget."""
    from paddleocr import PaddleOCR

    started = time.perf_counter()
    pipeline = PaddleOCR(
        text_detection_model_name="PP-OCRv6_tiny_det",
        text_recognition_model_name="PP-OCRv6_tiny_rec",
        device="cpu",
        enable_hpi=True,
        cpu_threads=PP_THREAD_BUDGET,
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
            text_det_limit_side_len=base.PP_LIMIT,
            text_det_limit_type="max",
        )
    )
    warmed = time.perf_counter()
    return pipeline, {
        "model_initialization_seconds": initialized - started,
        "warmup_seconds": warmed - initialized,
    }


def run_priority_tesseract(image: Image.Image) -> tuple[str, dict[str, float]]:
    """Run the unchanged primary OCR with its original ten-thread ceiling."""
    os.environ["OMP_THREAD_LIMIT"] = str(TESSERACT_THREAD_BUDGET)
    before_cpu = _cpu_children()
    started = time.perf_counter()
    output = pytesseract.image_to_string(
        image,
        lang="eng",
        config="--oem 1 --psm 3",
    )
    wall = time.perf_counter() - started
    cpu = max(0.0, _cpu_children() - before_cpu)
    return base.normalize_text(output), {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
    }


def model_file_manifest() -> dict[str, Any]:
    """Hash every local file used by the two official PP-OCR models."""
    root = Path.home() / ".paddlex" / "official_models"
    models = ("PP-OCRv6_tiny_det", "PP-OCRv6_tiny_rec")
    entries: list[dict[str, Any]] = []
    for model in models:
        model_root = root / model
        if not model_root.is_dir():
            raise RuntimeError(f"model directory missing: {model_root}")
        files = sorted(path for path in model_root.rglob("*") if path.is_file())
        if not files:
            raise RuntimeError(f"model directory is empty: {model_root}")
        for path in files:
            entries.append(
                {
                    "model": model,
                    "path": path.relative_to(model_root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return {
        "root_role": "runtime model files",
        "entries": entries,
        "aggregate_sha256": sha256_bytes(
            canonical_json(entries).encode("utf-8")
        ),
    }


def decision_from(report: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute gates without treating an older output snapshot as an oracle."""
    evaluation = report["evaluation"]
    policy = evaluation["policy"]
    reduction = evaluation["false_acceptance_error_reduction_factor"]
    loo = report["leave_one_page_out"]
    parity = report["parity"]
    runtime = report["runtime"]

    quality_gate = bool(
        (reduction is None or float(reduction) >= MIN_ERROR_REDUCTION)
        and float(policy["precision"]) >= MIN_PRECISION
        and float(policy["reference_coverage"]) >= MIN_REFERENCE_COVERAGE
        and int(policy["prediction_count"]) >= MIN_ACCEPTED
        and int(loo["passes"]) >= MIN_LOO_PASSES
    )
    concurrency_parity_gate = bool(
        parity["isolated_parallel_text_hashes_equal"]
    )
    frozen_drift_detected = bool(
        float(parity["tesseract_vs_frozen_speed_frontier"]["f1"])
        < base.MIN_FROZEN_PARITY_F1
        or float(parity["pp_1024_vs_frozen_speed_frontier"]["f1"])
        < base.MIN_FROZEN_PARITY_F1
    )
    runtime_gate = bool(
        float(runtime["pair_ratio_to_tesseract"]) <= base.MAX_PAIR_RATIO
        and float(runtime["mean_extra_wall_seconds_per_page"])
        <= base.MAX_MEAN_EXTRA_SECONDS
        and float(runtime["p90_page_extra_wall_seconds"])
        <= base.MAX_P90_EXTRA_SECONDS
        and concurrency_parity_gate
    )
    promotion_gate = quality_gate and runtime_gate
    verdict = (
        "PASS_BALANCED_PARALLEL_NUMERIC_PROOF_10X"
        if promotion_gate
        else (
            "QUALITY_PASS_BALANCED_RUNTIME_FAILED"
            if quality_gate
            else "BALANCED_PARALLEL_NUMERIC_PROOF_QUALITY_FAILED"
        )
    )
    return {
        "verdict": verdict,
        "quality_gate": quality_gate,
        "concurrency_parity_gate": concurrency_parity_gate,
        "frozen_drift_detected": frozen_drift_detected,
        "runtime_gate": runtime_gate,
        "promotion_gate": promotion_gate,
        "automatic_production_change": False,
        "next_experiment": (
            "open an untouched Honduran numeric holdout"
            if promotion_gate
            else "inspect the failed frozen gate without weakening it"
        ),
    }


def stable_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"environment", "stable_payload_sha256"}
    }


def finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the asymmetric resource contract and recompute all decisions."""
    report["schema"] = SCHEMA
    report["runtime_contract"].update(
        {
            "tesseract_thread_budget": TESSERACT_THREAD_BUDGET,
            "pp_thread_budget": PP_THREAD_BUDGET,
            "resource_policy": (
                "protect primary Tesseract throughput; verifier receives one "
                "CPU thread so aggregate demand fits the runner"
            ),
        }
    )
    report["runtime_contract"].pop("thread_budget_per_engine", None)
    report["gates"].update(
        {
            "older_frozen_output_identity": "diagnostic_only",
            "blocking_concurrency_parity": (
                "isolated and parallel normalized output hashes must be exact"
            ),
        }
    )
    report["model_manifest"] = model_file_manifest()
    report["decision"] = decision_from(report)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(stable_payload(report)).encode("utf-8")
    )
    report["environment"].update(
        {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "tesseract": subprocess.check_output(
                ["tesseract", "--version"],
                text=True,
                stderr=subprocess.STDOUT,
            ).splitlines()[0],
        }
    )
    return report


def build_report(
    quality_report_path: Path,
    speed_frontier_report_path: Path,
    quality_artifact_sha256: str,
    speed_artifact_sha256: str,
) -> dict[str, Any]:
    """Execute the same benchmark with only the PP thread budget changed."""
    original_make_pipeline = base.make_pipeline
    original_run_tesseract = base.run_tesseract
    try:
        base.make_pipeline = make_balanced_pipeline
        base.run_tesseract = run_priority_tesseract
        report = base.build_report(
            quality_report_path,
            speed_frontier_report_path,
            quality_artifact_sha256,
            speed_artifact_sha256,
        )
    finally:
        base.make_pipeline = original_make_pipeline
        base.run_tesseract = original_run_tesseract
    return finalize_report(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--speed-frontier-report", type=Path, required=True)
    parser.add_argument("--quality-artifact-sha256", required=True)
    parser.add_argument("--speed-artifact-sha256", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_numeric_parallel_10x_v1/run_balanced"),
    )
    args = parser.parse_args()
    report = build_report(
        args.quality_report,
        args.speed_frontier_report,
        args.quality_artifact_sha256,
        args.speed_artifact_sha256,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "balanced_parallel_numeric_benchmark.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "balanced_parallel_numeric_benchmark.sha256").write_text(
        f"{sha256_file(path)}  balanced_parallel_numeric_benchmark.json\n",
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
                "model_manifest": report["model_manifest"],
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
