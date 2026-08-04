"""Explicit one-thread Paddle Static verifier for numeric evidence.

This module corrects an invalid HPI experiment in which `cpu_threads=1` was
ignored and OpenVINO still used ten threads. It runs the same independent
full-page verifier through the documented `paddle_static` engine with an
authoritative one-thread `engine_config`.

Logic Power remains a development-time planner and is absent from runtime.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ocr_god_10x_quality_v1.full_content_quality import (
    canonical_json,
    sha256_bytes,
    sha256_file,
)
from ocr_numeric_parallel_10x_v1 import benchmark as base
from ocr_numeric_parallel_10x_v1 import balanced

SCHEMA = "ocr-numeric-parallel-static-10x/benchmark/1"
PP_ENGINE = "paddle_static"
PP_ENGINE_CONFIG = {
    "device_type": "cpu",
    "cpu_threads": balanced.PP_THREAD_BUDGET,
    "run_mode": "mkldnn",
}
MAX_PP_EFFECTIVE_CPU_PARALLELISM = 1.25


def make_static_pipeline() -> tuple[Any, dict[str, float]]:
    """Create the frozen PP verifier with explicit one-thread Paddle Inference."""
    from paddleocr import PaddleOCR

    started = time.perf_counter()
    pipeline = PaddleOCR(
        text_detection_model_name="PP-OCRv6_tiny_det",
        text_recognition_model_name="PP-OCRv6_tiny_rec",
        device="cpu",
        engine=PP_ENGINE,
        engine_config=PP_ENGINE_CONFIG,
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


def thread_evidence(report: Mapping[str, Any]) -> dict[str, Any]:
    """Measure PP CPU demand independently in isolated and concurrent modes."""
    isolated_wall = sum(
        float(page["isolated"]["pp_1024"]["runtime"]["wall_seconds"])
        for page in report["pages"]
    )
    isolated_cpu = sum(
        float(page["isolated"]["pp_1024"]["runtime"]["cpu_seconds"])
        for page in report["pages"]
    )
    parallel_wall = sum(
        float(page["parallel"]["pp_1024"]["runtime"]["wall_seconds"])
        for page in report["pages"]
    )
    parallel_cpu = sum(
        float(page["parallel"]["pp_1024"]["runtime"]["cpu_seconds"])
        for page in report["pages"]
    )
    isolated_effective = isolated_cpu / max(isolated_wall, 1e-15)
    parallel_effective = parallel_cpu / max(parallel_wall, 1e-15)
    maximum_observed = max(isolated_effective, parallel_effective)
    return {
        "engine": PP_ENGINE,
        "engine_config": dict(PP_ENGINE_CONFIG),
        "isolated_wall_seconds": isolated_wall,
        "isolated_cpu_seconds": isolated_cpu,
        "isolated_effective_cpu_parallelism": isolated_effective,
        "parallel_wall_seconds": parallel_wall,
        "parallel_cpu_seconds": parallel_cpu,
        "parallel_effective_cpu_parallelism": parallel_effective,
        "maximum_observed_effective_cpu_parallelism": maximum_observed,
        "maximum_allowed_effective_cpu_parallelism": (
            MAX_PP_EFFECTIVE_CPU_PARALLELISM
        ),
        "passes": maximum_observed <= MAX_PP_EFFECTIVE_CPU_PARALLELISM,
    }


def decision_from(report: Mapping[str, Any]) -> dict[str, Any]:
    """Extend the unchanged balanced gates with proof of the one-thread limit."""
    prior = balanced.decision_from(report)
    thread_gate = bool(report["thread_evidence"]["passes"])
    runtime_gate = bool(prior["runtime_gate"] and thread_gate)
    promotion_gate = bool(prior["quality_gate"] and runtime_gate)
    verdict = (
        "PASS_STATIC_ONE_THREAD_NUMERIC_PROOF_10X"
        if promotion_gate
        else (
            "QUALITY_PASS_STATIC_RUNTIME_FAILED"
            if prior["quality_gate"]
            else "STATIC_NUMERIC_PROOF_QUALITY_FAILED"
        )
    )
    return {
        **prior,
        "verdict": verdict,
        "thread_gate": thread_gate,
        "runtime_gate": runtime_gate,
        "promotion_gate": promotion_gate,
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


def build_report(
    quality_report_path: Path,
    speed_frontier_report_path: Path,
    quality_artifact_sha256: str,
    speed_artifact_sha256: str,
) -> dict[str, Any]:
    original_pipeline = balanced.make_balanced_pipeline
    try:
        balanced.make_balanced_pipeline = make_static_pipeline
        report = balanced.build_report(
            quality_report_path,
            speed_frontier_report_path,
            quality_artifact_sha256,
            speed_artifact_sha256,
        )
    finally:
        balanced.make_balanced_pipeline = original_pipeline

    report["schema"] = SCHEMA
    report["runtime_contract"].update(
        {
            "pp_inference_engine": PP_ENGINE,
            "pp_engine_config": dict(PP_ENGINE_CONFIG),
            "hpi_enabled": False,
            "thread_limit_validation": (
                "measured PP CPU seconds / PP wall seconds must not exceed "
                f"{MAX_PP_EFFECTIVE_CPU_PARALLELISM}"
            ),
        }
    )
    report["thread_evidence"] = thread_evidence(report)
    report["decision"] = decision_from(report)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(stable_payload(report)).encode("utf-8")
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--speed-frontier-report", type=Path, required=True)
    parser.add_argument("--quality-artifact-sha256", required=True)
    parser.add_argument("--speed-artifact-sha256", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_numeric_parallel_static_v1/run"),
    )
    args = parser.parse_args()
    report = build_report(
        args.quality_report,
        args.speed_frontier_report,
        args.quality_artifact_sha256,
        args.speed_artifact_sha256,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "static_parallel_numeric_benchmark.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "static_parallel_numeric_benchmark.sha256").write_text(
        f"{sha256_file(path)}  static_parallel_numeric_benchmark.json\n",
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
                "thread_evidence": report["thread_evidence"],
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
