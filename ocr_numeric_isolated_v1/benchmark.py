"""Independent numeric verifier in a spawned process with disjoint CPU sets.

The baseline charged to the experiment is the current all-CPU Tesseract pass.
For the candidate runtime, a persistent Paddle Static verifier is pinned to one
CPU while Tesseract and its subprocess inherit the other CPUs. The two engines
share the raster page but no boxes, crops, segmentation, or OCR output.

Logic Power is a development-time planner only and is absent from runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import resource
import subprocess
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image
import pytesseract

from ocr_god_10x_quality_v1.full_content_quality import (
    canonical_json,
    number_tokens,
    normalize_text,
    sha256_bytes,
    sha256_file,
)
from ocr_numeric_parallel_10x_v1 import benchmark as prior
from ocr_numeric_proof_10x_v1.policy import (
    MIN_ACCEPTED,
    MIN_ERROR_REDUCTION,
    MIN_LOO_PASSES,
    MIN_PRECISION,
    MIN_REFERENCE_COVERAGE,
    accepted_counter,
    multiset_metrics,
)

SCHEMA = "ocr-numeric-isolated-10x/benchmark/1"
DATASET_ID = "opendatalab/OmniDocBench"
DATASET_REVISION = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"
ANNOTATION_SHA256 = "a45cd84b04ad8b793e775089640e6b681209abea33ead54c1828ddca35fae496"
PP_LIMIT = 1024
TESSERACT_THREAD_CEILING = 10
PP_THREAD_BUDGET = 1
MAX_PP_EFFECTIVE_CPU_PARALLELISM = 1.25
MAX_PAIR_RATIO = 1.12
MAX_MEAN_EXTRA_SECONDS = 0.30
MAX_P90_EXTRA_SECONDS = 0.60
LOO_MIN_ACCEPTED = 250
WORKER_READY_TIMEOUT_SECONDS = 240.0
WORKER_RESULT_TIMEOUT_SECONDS = 120.0


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


def model_file_manifest() -> dict[str, Any]:
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


def _pp_text(pipeline: Any, image_array: Any) -> tuple[str, dict[str, Any]]:
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
    text = "\n".join(value for value in texts if value)
    return text, {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "effective_cpu_parallelism": cpu / max(wall, 1e-15),
        "line_count": len(texts),
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "prediction_sha256": _sha256_text(text),
        "affinity": sorted(int(value) for value in os.sched_getaffinity(0)),
    }


def verifier_worker(
    connection: Any,
    cpu_id: int,
    image_paths: Mapping[str, str],
) -> None:
    """Persistent one-CPU Paddle worker; every failure is returned explicitly."""
    try:
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["OPENBLAS_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"
        os.environ["OMP_THREAD_LIMIT"] = "1"
        os.sched_setaffinity(0, {int(cpu_id)})

        import numpy as np
        from paddleocr import PaddleOCR

        started = time.perf_counter()
        pipeline = PaddleOCR(
            text_detection_model_name="PP-OCRv6_tiny_det",
            text_recognition_model_name="PP-OCRv6_tiny_rec",
            device="cpu",
            engine="paddle_static",
            engine_config={
                "device_type": "cpu",
                "cpu_threads": PP_THREAD_BUDGET,
                "run_mode": "mkldnn",
            },
            text_recognition_batch_size=32,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        initialized = time.perf_counter()
        arrays: dict[str, Any] = {}
        for page_id, path_text in image_paths.items():
            with Image.open(path_text) as source:
                arrays[page_id] = np.asarray(source.convert("RGB"))
        loaded = time.perf_counter()
        blank = np.full((256, 1024, 3), 255, dtype=np.uint8)
        list(
            pipeline.predict(
                blank,
                text_det_limit_side_len=PP_LIMIT,
                text_det_limit_type="max",
            )
        )
        warmed = time.perf_counter()
        connection.send(
            {
                "kind": "ready",
                "pid": os.getpid(),
                "affinity": sorted(int(value) for value in os.sched_getaffinity(0)),
                "initialization": {
                    "model_initialization_seconds": initialized - started,
                    "image_preload_seconds": loaded - initialized,
                    "warmup_seconds": warmed - loaded,
                },
                "model_manifest": model_file_manifest(),
            }
        )

        while True:
            message = connection.recv()
            operation = message.get("operation")
            if operation == "stop":
                connection.send({"kind": "stopped", "pid": os.getpid()})
                break
            if operation != "run":
                raise RuntimeError(f"unknown worker operation: {operation!r}")
            request_id = str(message["request_id"])
            page_id = str(message["page_id"])
            if page_id not in arrays:
                raise KeyError(f"unknown page id: {page_id}")
            text, runtime = _pp_text(pipeline, arrays[page_id])
            connection.send(
                {
                    "kind": "result",
                    "request_id": request_id,
                    "page_id": page_id,
                    "text": text,
                    "runtime": runtime,
                }
            )
    except BaseException as exc:
        try:
            connection.send(
                {
                    "kind": "fatal",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
        except BaseException:
            pass
    finally:
        connection.close()


@contextmanager
def process_affinity(cpus: Sequence[int]):
    before = set(int(value) for value in os.sched_getaffinity(0))
    target = set(int(value) for value in cpus)
    if not target:
        raise RuntimeError("empty CPU affinity target")
    os.sched_setaffinity(0, target)
    try:
        observed = set(int(value) for value in os.sched_getaffinity(0))
        if observed != target:
            raise RuntimeError(f"affinity mismatch: {observed} != {target}")
        yield
    finally:
        os.sched_setaffinity(0, before)


def run_tesseract(
    image: Image.Image,
    expected_affinity: Sequence[int],
) -> dict[str, Any]:
    observed = sorted(int(value) for value in os.sched_getaffinity(0))
    expected = sorted(int(value) for value in expected_affinity)
    if observed != expected:
        raise RuntimeError(f"Tesseract parent affinity mismatch: {observed} != {expected}")
    os.environ["OMP_THREAD_LIMIT"] = str(TESSERACT_THREAD_CEILING)
    before_cpu = _cpu_children()
    started = time.perf_counter()
    output = pytesseract.image_to_string(
        image,
        lang="eng",
        config="--oem 1 --psm 3",
    )
    wall = time.perf_counter() - started
    cpu = max(0.0, _cpu_children() - before_cpu)
    text = normalize_text(output)
    return {
        "text": text,
        "runtime": {
            "wall_seconds": wall,
            "cpu_seconds": cpu,
            "effective_cpu_parallelism": cpu / max(wall, 1e-15),
            "parent_affinity": observed,
            "prediction_sha256": _sha256_text(text),
        },
    }


def _receive(connection: Any, timeout: float) -> Mapping[str, Any]:
    if not connection.poll(timeout):
        raise TimeoutError(f"verifier worker did not respond within {timeout} seconds")
    message = connection.recv()
    if message.get("kind") == "fatal":
        raise RuntimeError(
            "verifier worker failed: "
            + str(message.get("error"))
            + "\n"
            + str(message.get("traceback"))
        )
    return message


def request_pp(
    connection: Any,
    request_id: str,
    page_id: str,
) -> dict[str, Any]:
    connection.send(
        {
            "operation": "run",
            "request_id": request_id,
            "page_id": page_id,
        }
    )
    message = _receive(connection, WORKER_RESULT_TIMEOUT_SECONDS)
    if message.get("kind") != "result":
        raise RuntimeError(f"unexpected worker response: {message}")
    if str(message.get("request_id")) != request_id:
        raise RuntimeError("worker request id mismatch")
    if str(message.get("page_id")) != page_id:
        raise RuntimeError("worker page id mismatch")
    return dict(message)


def run_parallel_pair(
    executor: ThreadPoolExecutor,
    connection: Any,
    image: Image.Image,
    page_id: str,
    primary_cpus: Sequence[int],
    request_id: str,
) -> dict[str, Any]:
    with process_affinity(primary_cpus):
        started = time.perf_counter()
        connection.send(
            {
                "operation": "run",
                "request_id": request_id,
                "page_id": page_id,
            }
        )
        future = executor.submit(run_tesseract, image, list(primary_cpus))
        pp_message = _receive(connection, WORKER_RESULT_TIMEOUT_SECONDS)
        tesseract = future.result()
        pair_wall = time.perf_counter() - started
    if pp_message.get("kind") != "result":
        raise RuntimeError(f"unexpected worker response: {pp_message}")
    if str(pp_message.get("request_id")) != request_id:
        raise RuntimeError("parallel worker request id mismatch")
    return {
        "pair_wall_seconds": pair_wall,
        "tesseract": tesseract,
        "pp_1024": dict(pp_message),
    }


def counter_parity(observed: Counter[str], reference: Counter[str]) -> dict[str, Any]:
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
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[index]


def runtime_metrics(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    all_core = sum(
        float(page["controls"]["all_core_tesseract"]["runtime"]["wall_seconds"])
        for page in pages
    )
    reserved = sum(
        float(page["controls"]["reserved_tesseract"]["runtime"]["wall_seconds"])
        for page in pages
    )
    pp_isolated = sum(
        float(page["controls"]["isolated_pp"]["runtime"]["wall_seconds"])
        for page in pages
    )
    pair = sum(float(page["parallel"]["pair_wall_seconds"]) for page in pages)
    extra_vs_all = [
        float(page["parallel"]["pair_wall_seconds"])
        - float(page["controls"]["all_core_tesseract"]["runtime"]["wall_seconds"])
        for page in pages
    ]
    extra_vs_reserved = [
        float(page["parallel"]["pair_wall_seconds"])
        - float(page["controls"]["reserved_tesseract"]["runtime"]["wall_seconds"])
        for page in pages
    ]
    ideal = sum(
        max(
            float(page["controls"]["reserved_tesseract"]["runtime"]["wall_seconds"]),
            float(page["controls"]["isolated_pp"]["runtime"]["wall_seconds"]),
        )
        for page in pages
    )
    count = max(len(pages), 1)
    extra_total = pair - all_core
    return {
        "pages": len(pages),
        "all_core_tesseract_total_wall_seconds": all_core,
        "all_core_tesseract_mean_wall_seconds_per_page": all_core / count,
        "reserved_tesseract_total_wall_seconds": reserved,
        "reserved_tesseract_mean_wall_seconds_per_page": reserved / count,
        "reservation_slowdown_ratio": reserved / max(all_core, 1e-15),
        "isolated_pp_total_wall_seconds": pp_isolated,
        "isolated_pp_mean_wall_seconds_per_page": pp_isolated / count,
        "sequential_all_core_plus_pp_seconds": all_core + pp_isolated,
        "parallel_pair_total_wall_seconds": pair,
        "parallel_pair_mean_wall_seconds_per_page": pair / count,
        "pair_ratio_to_all_core_tesseract": pair / max(all_core, 1e-15),
        "pair_ratio_to_reserved_tesseract": pair / max(reserved, 1e-15),
        "mean_extra_wall_seconds_per_page": extra_total / count,
        "p90_extra_wall_seconds_per_page": percentile(extra_vs_all, 0.90),
        "maximum_extra_wall_seconds_per_page": max(extra_vs_all) if extra_vs_all else 0.0,
        "mean_extra_vs_reserved_seconds_per_page": sum(extra_vs_reserved) / count,
        "parallel_speedup_vs_sequential": (all_core + pp_isolated) / max(pair, 1e-15),
        "pp_wall_fraction_hidden_vs_all_core": 1.0 - max(extra_total, 0.0) / max(pp_isolated, 1e-15),
        "pp_wall_fraction_hidden_vs_reserved": 1.0 - max(pair - reserved, 0.0) / max(pp_isolated, 1e-15),
        "ideal_disjoint_pair_total_wall_seconds": ideal,
        "observed_to_ideal_pair_ratio": pair / max(ideal, 1e-15),
        "page_extra_vs_all_core_seconds": extra_vs_all,
        "page_extra_vs_reserved_seconds": extra_vs_reserved,
    }


def affinity_evidence(
    pages: Sequence[Mapping[str, Any]],
    original_cpus: Sequence[int],
    primary_cpus: Sequence[int],
    verifier_cpu: int,
    worker_ready: Mapping[str, Any],
) -> dict[str, Any]:
    original = sorted(int(value) for value in original_cpus)
    primary = sorted(int(value) for value in primary_cpus)
    verifier = [int(verifier_cpu)]
    all_core_ok = all(
        page["controls"]["all_core_tesseract"]["runtime"]["parent_affinity"] == original
        for page in pages
    )
    reserved_ok = all(
        page["controls"]["reserved_tesseract"]["runtime"]["parent_affinity"] == primary
        for page in pages
    )
    parallel_t_ok = all(
        page["parallel"]["tesseract"]["runtime"]["parent_affinity"] == primary
        for page in pages
    )
    verifier_ok = all(
        page["controls"]["isolated_pp"]["runtime"]["affinity"] == verifier
        and page["parallel"]["pp_1024"]["runtime"]["affinity"] == verifier
        for page in pages
    )
    disjoint = not (set(primary) & set(verifier))
    union_complete = set(primary) | set(verifier) == set(original)
    worker_ready_ok = sorted(worker_ready.get("affinity") or []) == verifier
    passes = bool(
        len(original) >= 4
        and len(primary) >= 3
        and len(verifier) == 1
        and disjoint
        and union_complete
        and worker_ready_ok
        and all_core_ok
        and reserved_ok
        and parallel_t_ok
        and verifier_ok
    )
    return {
        "original_allowed_cpus": original,
        "primary_tesseract_cpus": primary,
        "verifier_cpus": verifier,
        "worker_reported_cpus": sorted(worker_ready.get("affinity") or []),
        "disjoint": disjoint,
        "union_complete": union_complete,
        "all_core_controls_correct": all_core_ok,
        "reserved_controls_correct": reserved_ok,
        "parallel_tesseract_correct": parallel_t_ok,
        "verifier_runs_correct": verifier_ok,
        "passes": passes,
    }


def thread_evidence(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    isolated_wall = sum(
        float(page["controls"]["isolated_pp"]["runtime"]["wall_seconds"])
        for page in pages
    )
    isolated_cpu = sum(
        float(page["controls"]["isolated_pp"]["runtime"]["cpu_seconds"])
        for page in pages
    )
    parallel_wall = sum(
        float(page["parallel"]["pp_1024"]["runtime"]["wall_seconds"])
        for page in pages
    )
    parallel_cpu = sum(
        float(page["parallel"]["pp_1024"]["runtime"]["cpu_seconds"])
        for page in pages
    )
    isolated_effective = isolated_cpu / max(isolated_wall, 1e-15)
    parallel_effective = parallel_cpu / max(parallel_wall, 1e-15)
    maximum = max(isolated_effective, parallel_effective)
    return {
        "isolated_wall_seconds": isolated_wall,
        "isolated_cpu_seconds": isolated_cpu,
        "isolated_effective_cpu_parallelism": isolated_effective,
        "parallel_wall_seconds": parallel_wall,
        "parallel_cpu_seconds": parallel_cpu,
        "parallel_effective_cpu_parallelism": parallel_effective,
        "maximum_observed_effective_cpu_parallelism": maximum,
        "maximum_allowed_effective_cpu_parallelism": MAX_PP_EFFECTIVE_CPU_PARALLELISM,
        "passes": maximum <= MAX_PP_EFFECTIVE_CPU_PARALLELISM,
    }


def output_parity(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tesseract_exact = all(
        page["controls"]["all_core_tesseract"]["runtime"]["prediction_sha256"]
        == page["controls"]["reserved_tesseract"]["runtime"]["prediction_sha256"]
        == page["parallel"]["tesseract"]["runtime"]["prediction_sha256"]
        for page in pages
    )
    pp_exact = all(
        page["controls"]["isolated_pp"]["runtime"]["prediction_sha256"]
        == page["parallel"]["pp_1024"]["runtime"]["prediction_sha256"]
        for page in pages
    )
    return {
        "tesseract_all_core_reserved_parallel_exact": tesseract_exact,
        "pp_isolated_parallel_exact": pp_exact,
        "passes": tesseract_exact and pp_exact,
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
    from huggingface_hub import hf_hub_download

    quality = json.loads(quality_report_path.read_text(encoding="utf-8"))
    speed = json.loads(speed_frontier_report_path.read_text(encoding="utf-8"))
    quality_rows = quality.get("observations") or []
    speed_rows = speed.get("observations") or []
    if len(quality_rows) != 20:
        raise RuntimeError(f"expected 20 quality pages, observed {len(quality_rows)}")
    page_ids = [str(row["page_id"]) for row in quality_rows]
    if len(set(page_ids)) != len(page_ids):
        raise RuntimeError("duplicate page identities")
    speed_by_page = {str(row["page_id"]): row for row in speed_rows}
    if set(speed_by_page) != set(page_ids):
        raise RuntimeError("speed and quality page sets differ")

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

    quality_by_page = {str(row["page_id"]): row for row in quality_rows}
    image_paths: dict[str, str] = {}
    images: dict[str, Image.Image] = {}
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
        image_paths[page_id] = str(image_path)
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        images[page_id] = image
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

    original_cpus = sorted(int(value) for value in os.sched_getaffinity(0))
    if len(original_cpus) < 4:
        raise RuntimeError(f"at least four allowed CPUs required, observed {original_cpus}")
    verifier_cpu = original_cpus[-1]
    primary_cpus = original_cpus[:-1]

    context = mp.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=True)
    worker = context.Process(
        target=verifier_worker,
        args=(child_connection, verifier_cpu, image_paths),
        name="pp-ocr-verifier",
    )
    worker.start()
    child_connection.close()
    worker_ready: Mapping[str, Any] | None = None
    pages: list[dict[str, Any]] = []
    try:
        worker_ready = _receive(parent_connection, WORKER_READY_TIMEOUT_SECONDS)
        if worker_ready.get("kind") != "ready":
            raise RuntimeError(f"unexpected worker initialization response: {worker_ready}")

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tesseract") as executor:
            executor.submit(lambda: None).result()
            for index, page_id in enumerate(page_ids):
                image = images[page_id]
                if index % 2 == 0:
                    with process_affinity(original_cpus):
                        all_core = run_tesseract(image, original_cpus)
                    with process_affinity(primary_cpus):
                        reserved = run_tesseract(image, primary_cpus)
                    isolated_pp = request_pp(
                        parent_connection,
                        f"isolated-{index:02d}",
                        page_id,
                    )
                    parallel = run_parallel_pair(
                        executor,
                        parent_connection,
                        image,
                        page_id,
                        primary_cpus,
                        f"parallel-{index:02d}",
                    )
                    order = "controls_then_parallel"
                else:
                    parallel = run_parallel_pair(
                        executor,
                        parent_connection,
                        image,
                        page_id,
                        primary_cpus,
                        f"parallel-{index:02d}",
                    )
                    isolated_pp = request_pp(
                        parent_connection,
                        f"isolated-{index:02d}",
                        page_id,
                    )
                    with process_affinity(primary_cpus):
                        reserved = run_tesseract(image, primary_cpus)
                    with process_affinity(original_cpus):
                        all_core = run_tesseract(image, original_cpus)
                    order = "parallel_then_controls"

                tesseract_text = str(parallel["tesseract"]["text"])
                pp_text = str(parallel["pp_1024"]["text"])
                tesseract_tokens = number_tokens(tesseract_text)
                pp_tokens = number_tokens(pp_text)
                accepted = accepted_counter(Counter(tesseract_tokens), Counter(pp_tokens))
                quality_row = quality_by_page[page_id]
                reference_tokens = number_tokens(str(quality_row["reference"]["full"]))
                frozen_row = speed_by_page[page_id]
                frozen_tesseract = number_tokens(
                    str(frozen_row["engines"]["tesseract"]["text"])
                )
                frozen_pp = number_tokens(
                    str(frozen_row["engines"]["max_1024"]["text"])
                )
                pages.append(
                    {
                        "page_id": page_id,
                        "crossover_order": order,
                        "reference_tokens": reference_tokens,
                        "tesseract_tokens": tesseract_tokens,
                        "pp_1024_tokens": pp_tokens,
                        "accepted_tokens": [
                            token
                            for token in sorted(accepted)
                            for _ in range(accepted[token])
                        ],
                        "frozen_tesseract_tokens": frozen_tesseract,
                        "frozen_pp_1024_tokens": frozen_pp,
                        "controls": {
                            "all_core_tesseract": all_core,
                            "reserved_tesseract": reserved,
                            "isolated_pp": isolated_pp,
                        },
                        "parallel": parallel,
                    }
                )
    finally:
        os.sched_setaffinity(0, set(original_cpus))
        if worker.is_alive():
            try:
                parent_connection.send({"operation": "stop"})
                if parent_connection.poll(20.0):
                    parent_connection.recv()
            except BaseException:
                pass
        worker.join(timeout=20.0)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10.0)
        parent_connection.close()

    if worker_ready is None:
        raise RuntimeError("worker did not initialize")
    if worker.exitcode not in (0, None):
        raise RuntimeError(f"verifier worker exit code: {worker.exitcode}")

    evaluation = evaluate_pages(pages)
    loo = loo_diagnostics(pages)
    runtime = runtime_metrics(pages)
    affinity = affinity_evidence(
        pages,
        original_cpus,
        primary_cpus,
        verifier_cpu,
        worker_ready,
    )
    threads = thread_evidence(pages)
    parity = output_parity(pages)

    actual_tesseract: Counter[str] = Counter()
    actual_pp: Counter[str] = Counter()
    frozen_tesseract: Counter[str] = Counter()
    frozen_pp: Counter[str] = Counter()
    for page in pages:
        actual_tesseract.update(str(value) for value in page["tesseract_tokens"])
        actual_pp.update(str(value) for value in page["pp_1024_tokens"])
        frozen_tesseract.update(str(value) for value in page["frozen_tesseract_tokens"])
        frozen_pp.update(str(value) for value in page["frozen_pp_1024_tokens"])
    drift = {
        "tesseract_vs_frozen_speed_frontier": counter_parity(actual_tesseract, frozen_tesseract),
        "pp_1024_vs_frozen_speed_frontier": counter_parity(actual_pp, frozen_pp),
        "blocking": False,
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
    runtime_gate = bool(
        float(runtime["pair_ratio_to_all_core_tesseract"]) <= MAX_PAIR_RATIO
        and float(runtime["mean_extra_wall_seconds_per_page"]) <= MAX_MEAN_EXTRA_SECONDS
        and float(runtime["p90_extra_wall_seconds_per_page"]) <= MAX_P90_EXTRA_SECONDS
    )
    promotion_gate = bool(
        quality_gate
        and runtime_gate
        and affinity["passes"]
        and threads["passes"]
        and parity["passes"]
    )
    verdict = (
        "PASS_PROCESS_ISOLATED_NUMERIC_PROOF_10X"
        if promotion_gate
        else (
            "QUALITY_PASS_PROCESS_RUNTIME_FAILED"
            if quality_gate
            else "PROCESS_ISOLATED_NUMERIC_PROOF_QUALITY_FAILED"
        )
    )

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "quality_report_sha256": sha256_file(quality_report_path),
            "quality_stable_payload_sha256": quality["stable_payload_sha256"],
            "quality_artifact_sha256": quality_artifact_sha256,
            "speed_frontier_report_sha256": sha256_file(speed_frontier_report_path),
            "speed_frontier_stable_payload_sha256": speed["stable_payload_sha256"],
            "speed_artifact_sha256": speed_artifact_sha256,
            "dataset_id": DATASET_ID,
            "dataset_revision": DATASET_REVISION,
            "annotation_sha256": ANNOTATION_SHA256,
        },
        "runtime_contract": {
            "charged_baseline": "Tesseract on every originally allowed CPU",
            "candidate_primary": "Tesseract pinned to all but one allowed CPU",
            "independent_verifier": "persistent spawned Paddle Static process pinned to one CPU",
            "pp_engine": "paddle_static",
            "pp_engine_config": {
                "device_type": "cpu",
                "cpu_threads": PP_THREAD_BUDGET,
                "run_mode": "mkldnn",
            },
            "pp_detection_limit_side_len": PP_LIMIT,
            "shared_boxes": False,
            "shared_crops": False,
            "shared_segmentation": False,
            "shared_output": False,
            "result_cache": False,
            "crossover_timing_design": True,
            "acceptance": "repeated canonical numeric intersection of two independent full-page OCR outputs",
            "all_other_numbers": "ABSTAIN_FROM_EVIDENCE_PROMOTION",
        },
        "gates": {
            "minimum_false_acceptance_error_reduction": MIN_ERROR_REDUCTION,
            "minimum_precision": MIN_PRECISION,
            "minimum_reference_coverage": MIN_REFERENCE_COVERAGE,
            "minimum_accepted_count": MIN_ACCEPTED,
            "minimum_leave_one_page_out_passes": MIN_LOO_PASSES,
            "maximum_pp_effective_cpu_parallelism": MAX_PP_EFFECTIVE_CPU_PARALLELISM,
            "maximum_pair_ratio_to_all_core_tesseract": MAX_PAIR_RATIO,
            "maximum_mean_extra_seconds_per_page": MAX_MEAN_EXTRA_SECONDS,
            "maximum_p90_extra_seconds_per_page": MAX_P90_EXTRA_SECONDS,
        },
        "worker_initialization_excluded_from_steady_state": worker_ready["initialization"],
        "worker_pid": worker_ready["pid"],
        "model_manifest": worker_ready["model_manifest"],
        "image_manifest": image_manifest,
        "pages": pages,
        "evaluation": evaluation,
        "leave_one_page_out": loo,
        "runtime": runtime,
        "affinity_evidence": affinity,
        "thread_evidence": threads,
        "output_parity": parity,
        "historical_drift_diagnostic": drift,
        "decision": {
            "verdict": verdict,
            "quality_gate": quality_gate,
            "runtime_gate": runtime_gate,
            "affinity_gate": affinity["passes"],
            "thread_gate": threads["passes"],
            "output_parity_gate": parity["passes"],
            "promotion_gate": promotion_gate,
            "automatic_production_change": False,
            "next_experiment": (
                "open an untouched Honduran numeric holdout"
                if promotion_gate
                else "inspect the failed frozen gate without weakening it"
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
        },
    }
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(stable_payload(report)).encode("utf-8")
    )
    report["environment"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "allowed_cpu_count": len(original_cpus),
        "multiprocessing_start_method": "spawn",
        "tesseract": subprocess.check_output(
            ["tesseract", "--version"],
            text=True,
            stderr=subprocess.STDOUT,
        ).splitlines()[0],
    }
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
        default=Path("ocr_numeric_isolated_v1/run"),
    )
    args = parser.parse_args()
    report = build_report(
        args.quality_report,
        args.speed_frontier_report,
        args.quality_artifact_sha256,
        args.speed_artifact_sha256,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "isolated_numeric_benchmark.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "isolated_numeric_benchmark.sha256").write_text(
        f"{sha256_file(path)}  isolated_numeric_benchmark.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(path),
                "evaluation": report["evaluation"],
                "leave_one_page_out": report["leave_one_page_out"],
                "runtime": report["runtime"],
                "affinity_evidence": report["affinity_evidence"],
                "thread_evidence": report["thread_evidence"],
                "output_parity": report["output_parity"],
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
