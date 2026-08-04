"""Direct-module batched PP-OCRv6 benchmark on the frozen real pages.

The general pipeline is decomposed into one batched text detector, deterministic
perspective crops, and one batched recognizer. This removes repeated Python and
pipeline orchestration while preserving the same official tiny models.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import resource
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np
from PIL import Image

from ocr_reading_order_real_v1.core import (
    ANNOTATION_FILE,
    DATASET_ID,
    EXPECTED_ANNOTATION_SHA256,
    PINNED_REVISION,
    canonical_json,
    sha256_bytes,
)
from ocr_reading_order_tesseract_v1.run_canary import page_from_raw, sha256_file

from .benchmark import (
    TARGET_PAGES,
    THREAD_BUDGET,
    _sha256_text,
    aggregate,
    page_metrics,
    reference_text,
    run_tesseract,
    select_pages,
)

SCHEMA = "ocr-god-10x/direct-batch/1"
SPECS: dict[str, tuple[int, int, int]] = {
    "direct_1536_b1": (1536, 1, 256),
    "direct_1536_b4": (1536, 4, 256),
    "direct_1024_b4": (1024, 4, 256),
    "direct_768_b4": (768, 4, 256),
    "direct_512_b4": (512, 4, 256),
}


def _cpu_self() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def unwrap(result: Any) -> Mapping[str, Any]:
    payload = result.json
    if callable(payload):
        payload = payload()
    if not isinstance(payload, Mapping):
        raise TypeError(f"unexpected result payload: {type(payload)!r}")
    inner = payload.get("res", payload)
    if not isinstance(inner, Mapping):
        raise TypeError("result payload does not contain a mapping")
    return inner


def order_points(poly: Sequence[Sequence[float]]) -> np.ndarray:
    points = np.asarray(poly, dtype=np.float32).reshape(4, 2)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).reshape(-1)
    ordered = np.empty((4, 2), dtype=np.float32)
    ordered[0] = points[int(np.argmin(sums))]
    ordered[2] = points[int(np.argmax(sums))]
    ordered[1] = points[int(np.argmin(diffs))]
    ordered[3] = points[int(np.argmax(diffs))]
    return ordered


def perspective_crop(image: np.ndarray, poly: Sequence[Sequence[float]]) -> np.ndarray:
    points = order_points(poly)
    width_top = np.linalg.norm(points[1] - points[0])
    width_bottom = np.linalg.norm(points[2] - points[3])
    height_right = np.linalg.norm(points[2] - points[1])
    height_left = np.linalg.norm(points[3] - points[0])
    width = max(2, int(round(max(width_top, width_bottom))))
    height = max(2, int(round(max(height_right, height_left))))
    target = np.asarray(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(points, target)
    crop = cv2.warpPerspective(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    if crop.shape[0] / max(crop.shape[1], 1) >= 1.5:
        crop = np.rot90(crop)
    return np.ascontiguousarray(crop)


def polygon_sort_key(poly: Sequence[Sequence[float]]) -> tuple[float, float]:
    points = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
    return float(points[:, 1].min()), float(points[:, 0].min())


def create_modules() -> tuple[Any, Any, dict[str, float]]:
    from paddleocr import TextDetection, TextRecognition

    started = time.perf_counter()
    detector = TextDetection(
        model_name="PP-OCRv6_tiny_det",
        device="cpu",
        enable_hpi=True,
        cpu_threads=THREAD_BUDGET,
    )
    detector_seconds = time.perf_counter() - started

    started = time.perf_counter()
    recognizer = TextRecognition(
        model_name="PP-OCRv6_tiny_rec",
        device="cpu",
        enable_hpi=True,
        cpu_threads=THREAD_BUDGET,
    )
    recognizer_seconds = time.perf_counter() - started
    return detector, recognizer, {
        "detector_seconds": detector_seconds,
        "recognizer_seconds": recognizer_seconds,
    }


def run_direct(
    detector: Any,
    recognizer: Any,
    images: Sequence[np.ndarray],
    *,
    limit: int,
    detection_batch: int,
    recognition_batch: int,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    started_cpu = _cpu_self()
    started_wall = time.perf_counter()
    detection_results = list(
        detector.predict(
            input=list(images),
            batch_size=detection_batch,
            limit_side_len=limit,
            limit_type="max",
        )
    )
    detection_wall = time.perf_counter() - started_wall
    detection_cpu = max(0.0, _cpu_self() - started_cpu)
    if len(detection_results) != len(images):
        raise AssertionError(
            f"detection denominator mismatch: {len(detection_results)} != {len(images)}"
        )

    crops: list[np.ndarray] = []
    crop_map: list[tuple[int, int]] = []
    page_polys: list[list[list[list[int]]]] = []
    page_scores: list[list[float]] = []
    crop_started = time.perf_counter()
    crop_cpu_started = _cpu_self()
    for page_index, (image, result) in enumerate(zip(images, detection_results, strict=True)):
        payload = unwrap(result)
        polys = [np.asarray(poly, dtype=np.float32).reshape(4, 2) for poly in payload.get("dt_polys", [])]
        scores = [float(value) for value in payload.get("dt_scores", [])]
        if len(polys) != len(scores):
            raise AssertionError("detection polygon and score denominators differ")
        order = sorted(range(len(polys)), key=lambda index: polygon_sort_key(polys[index]))
        ordered_polys = [polys[index] for index in order]
        ordered_scores = [scores[index] for index in order]
        page_polys.append(
            [[[int(round(x)), int(round(y))] for x, y in poly] for poly in ordered_polys]
        )
        page_scores.append(ordered_scores)
        for local_index, poly in enumerate(ordered_polys):
            crop = perspective_crop(image, poly)
            if crop.size == 0:
                raise AssertionError("empty perspective crop")
            crop_map.append((page_index, local_index))
            crops.append(crop)
    crop_wall = time.perf_counter() - crop_started
    crop_cpu = max(0.0, _cpu_self() - crop_cpu_started)

    recognition_started = time.perf_counter()
    recognition_cpu_started = _cpu_self()
    recognition_results = list(
        recognizer.predict(input=crops, batch_size=recognition_batch)
    ) if crops else []
    recognition_wall = time.perf_counter() - recognition_started
    recognition_cpu = max(0.0, _cpu_self() - recognition_cpu_started)
    if len(recognition_results) != len(crops):
        raise AssertionError(
            f"recognition denominator mismatch: {len(recognition_results)} != {len(crops)}"
        )

    page_texts: list[list[str]] = [[] for _ in images]
    page_rec_scores: list[list[float]] = [[] for _ in images]
    for (page_index, _local_index), result in zip(crop_map, recognition_results, strict=True):
        payload = unwrap(result)
        text = " ".join(str(payload.get("rec_text") or "").split())
        score = float(payload.get("rec_score") or 0.0)
        if text:
            page_texts[page_index].append(text)
            page_rec_scores[page_index].append(score)

    outputs = ["\n".join(values) for values in page_texts]
    per_page: list[dict[str, Any]] = []
    page_count = max(len(images), 1)
    for index in range(len(images)):
        per_page.append(
            {
                "detected_lines": len(page_polys[index]),
                "recognised_lines": len(page_texts[index]),
                "mean_detection_score": (
                    sum(page_scores[index]) / len(page_scores[index])
                    if page_scores[index]
                    else 0.0
                ),
                "mean_recognition_score": (
                    sum(page_rec_scores[index]) / len(page_rec_scores[index])
                    if page_rec_scores[index]
                    else 0.0
                ),
                "polys": page_polys[index],
                "detection_scores": page_scores[index],
                "recognition_scores": page_rec_scores[index],
                "runtime": {
                    "wall_seconds": (detection_wall + crop_wall + recognition_wall) / page_count,
                    "cpu_seconds": (detection_cpu + crop_cpu + recognition_cpu) / page_count,
                },
            }
        )
    totals = {
        "detection_wall_seconds": detection_wall,
        "crop_wall_seconds": crop_wall,
        "recognition_wall_seconds": recognition_wall,
        "total_wall_seconds": detection_wall + crop_wall + recognition_wall,
        "detection_cpu_seconds": detection_cpu,
        "crop_cpu_seconds": crop_cpu,
        "recognition_cpu_seconds": recognition_cpu,
        "total_cpu_seconds": detection_cpu + crop_cpu + recognition_cpu,
        "pages": len(images),
        "crops": len(crops),
        "detection_batch": detection_batch,
        "recognition_batch": recognition_batch,
        "limit_side_len": limit,
    }
    return outputs, per_page, totals


def direct_gate(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    speedup = float(baseline["total_wall_seconds"]) / max(float(candidate["total_wall_seconds"]), 1e-15)
    cpu_speedup = float(baseline["total_cpu_seconds"]) / max(float(candidate["total_cpu_seconds"]), 1e-15)
    word_error = float(candidate["word_micro"]["error"])
    numeric_error = float(candidate["numeric_micro"]["error"])
    baseline_word_error = float(baseline["word_micro"]["error"])
    baseline_numeric_error = float(baseline["numeric_micro"]["error"])
    return {
        "wall_speedup_vs_tesseract": speedup,
        "cpu_speedup_vs_tesseract": cpu_speedup,
        "wall_speed_10x": speedup >= 10.0,
        "cpu_speed_10x": cpu_speedup >= 10.0,
        "word_quality_10x": word_error <= baseline_word_error / 10.0 + 1e-15,
        "numeric_quality_10x": numeric_error <= baseline_numeric_error / 10.0 + 1e-15,
        "word_f1_not_worse": float(candidate["word_micro"]["f1"]) >= float(baseline["word_micro"]["f1"]) - 1e-15,
        "numeric_f1_not_worse": float(candidate["numeric_micro"]["f1"]) >= float(baseline["numeric_micro"]["f1"]) - 1e-15,
        "no_extra_catastrophic_pages": int(candidate["catastrophic_pages"]) <= int(baseline["catastrophic_pages"]),
        "full_10x_gate": (
            speedup >= 10.0
            and word_error <= baseline_word_error / 10.0 + 1e-15
            and numeric_error <= baseline_numeric_error / 10.0 + 1e-15
            and int(candidate["catastrophic_pages"]) <= int(baseline["catastrophic_pages"])
        ),
    }


def build_report() -> dict[str, Any]:
    from huggingface_hub import hf_hub_download

    annotation = Path(
        hf_hub_download(
            DATASET_ID,
            ANNOTATION_FILE,
            repo_type="dataset",
            revision=PINNED_REVISION,
        )
    )
    if sha256_file(annotation) != EXPECTED_ANNOTATION_SHA256:
        raise RuntimeError("annotation hash mismatch")
    raw = json.loads(annotation.read_text(encoding="utf-8"))
    eligible = [page for item in raw if (page := page_from_raw(item)) is not None]
    selected = select_pages(eligible)

    images: list[np.ndarray] = []
    image_paths: list[Path] = []
    references: list[str] = []
    for page in selected:
        dataset_path = page.page_id if page.page_id.startswith("images/") else f"images/{page.page_id}"
        path = Path(
            hf_hub_download(
                DATASET_ID,
                dataset_path,
                repo_type="dataset",
                revision=PINNED_REVISION,
            )
        )
        image_paths.append(path)
        images.append(np.asarray(Image.open(path).convert("RGB")))
        references.append(reference_text(page))

    detector, recognizer, initialization = create_modules()
    # Warm both modules outside measured runtime.
    list(
        detector.predict(
            input=[np.full((256, 1024, 3), 255, dtype=np.uint8)],
            batch_size=1,
            limit_side_len=1024,
            limit_type="max",
        )
    )
    list(
        recognizer.predict(
            input=[np.full((48, 320, 3), 255, dtype=np.uint8)],
            batch_size=1,
        )
    )

    rows: list[dict[str, Any]] = []
    for page, path, reference, image in zip(selected, image_paths, references, images, strict=True):
        tesseract_text, runtime = run_tesseract(Image.fromarray(image))
        rows.append(
            {
                "page_id": page.page_id,
                "layout": page.layout,
                "domain": page.domain,
                "image_sha256": sha256_file(path),
                "image_bytes": path.stat().st_size,
                "image_width": int(image.shape[1]),
                "image_height": int(image.shape[0]),
                "reference_text": reference,
                "reference_sha256": _sha256_text(reference),
                "engines": {
                    "tesseract": {
                        "text": tesseract_text,
                        "runtime": runtime,
                        "metrics": page_metrics(reference, tesseract_text),
                    }
                },
            }
        )

    totals: dict[str, Any] = {}
    for name, (limit, detection_batch, recognition_batch) in SPECS.items():
        outputs, per_page, total = run_direct(
            detector,
            recognizer,
            images,
            limit=limit,
            detection_batch=detection_batch,
            recognition_batch=recognition_batch,
        )
        totals[name] = total
        for row, text, details in zip(rows, outputs, per_page, strict=True):
            row["engines"][name] = {
                "text": text,
                "runtime": details.pop("runtime"),
                "metrics": page_metrics(str(row["reference_text"]), text),
                "details": details,
            }

    engine_names = ["tesseract", *SPECS]
    aggregates = {name: aggregate(rows, name) for name in engine_names}
    baseline = aggregates["tesseract"]
    gates = {
        name: direct_gate(baseline, aggregates[name])
        for name in SPECS
    }
    passing = sorted(name for name, gate in gates.items() if gate["full_10x_gate"])
    speed_passing = sorted(name for name, gate in gates.items() if gate["wall_speed_10x"])
    fidelity_candidates = [
        (
            float(aggregates[name]["total_wall_seconds"]),
            -float(aggregates[name]["word_micro"]["f1"]),
            name,
        )
        for name in SPECS
        if gates[name]["word_f1_not_worse"]
        and gates[name]["numeric_f1_not_worse"]
        and gates[name]["no_extra_catastrophic_pages"]
    ]
    best_fidelity = min(fidelity_candidates)[2] if fidelity_candidates else None
    fastest = min(SPECS, key=lambda name: float(aggregates[name]["total_wall_seconds"]))
    if passing:
        verdict = "PASS_10X_DEVELOPMENT"
        next_experiment = "freeze the lowest-cost passing candidate and open a new untouched holdout"
    elif speed_passing:
        verdict = "DIRECT_BATCH_SPEED_PASS_QUALITY_RESCUE_REQUIRED"
        next_experiment = "freeze the fastest 10x detector/recognizer path and test visual or evidence-aware rescue"
    else:
        verdict = "DIRECT_BATCH_10X_NOT_REACHED"
        next_experiment = "test multi-process throughput with equal core budget and direct detector-only reuse"

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "dataset": {
            "id": DATASET_ID,
            "revision": PINNED_REVISION,
            "annotation_sha256": EXPECTED_ANNOTATION_SHA256,
            "role": "development",
            "selection": "same frozen 20-page layout round-robin",
            "selected_page_ids": [page.page_id for page in selected],
            "selected_page_ids_sha256": sha256_bytes(
                canonical_json([page.page_id for page in selected]).encode("utf-8")
            ),
        },
        "thread_budget": THREAD_BUDGET,
        "specs": {
            name: {
                "limit_side_len": spec[0],
                "detection_batch": spec[1],
                "recognition_batch": spec[2],
            }
            for name, spec in SPECS.items()
        },
        "initialization_seconds": initialization,
        "direct_stage_totals": totals,
        "observations": rows,
        "aggregate": aggregates,
        "decision": {
            "verdict": verdict,
            "passing_candidates": passing,
            "speed_passing_candidates": speed_passing,
            "best_fidelity_candidate": best_fidelity,
            "fastest_candidate": fastest,
            "gates": gates,
            "next_experiment": next_experiment,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "native_text_counted": False,
            "cache_hits_counted": False,
            "repeated_pages_counted": False,
            "logic_power_in_runtime": False,
        },
    }
    payload["stable_payload_sha256"] = _sha256_text(canonical_json(payload))
    payload["environment"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tesseract": subprocess.check_output(
            ["tesseract", "--version"],
            text=True,
            stderr=subprocess.STDOUT,
        ).splitlines()[0],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_god_10x_v2/run/direct_batch"),
    )
    args = parser.parse_args()
    report = build_report()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "direct_batch.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "direct_batch.sha256").write_text(
        f"{sha256_file(path)}  direct_batch.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(path),
                "decision": report["decision"],
                "aggregate": report["aggregate"],
                "direct_stage_totals": report["direct_stage_totals"],
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
