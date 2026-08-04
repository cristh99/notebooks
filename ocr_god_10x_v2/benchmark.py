"""Same-page, same-runner OCR speed and quality benchmark.

This is a development benchmark. It compares one Tesseract baseline with three
frozen PP-OCRv6 detector/recognizer combinations on the same 20 unique raster
pages and CPU runner. Logic Power is not imported by runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import resource
import subprocess
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from PIL import Image
import pytesseract

from ocr_reading_order_real_v1.core import (
    ANNOTATION_FILE,
    DATASET_ID,
    EXPECTED_ANNOTATION_SHA256,
    PINNED_REVISION,
    canonical_json,
    sha256_bytes,
)
from ocr_reading_order_tesseract_v1.run_canary import (
    GTPage,
    normalize_text,
    page_from_raw,
    sha256_file,
)

SCHEMA = "ocr-god-10x/real-benchmark/1"
TARGET_PAGES = 20
THREAD_BUDGET = 10
MODEL_SPECS: dict[str, tuple[str, str]] = {
    "pp_tiny": ("PP-OCRv6_tiny_det", "PP-OCRv6_tiny_rec"),
    "pp_small_rec": ("PP-OCRv6_tiny_det", "PP-OCRv6_small_rec"),
    "pp_medium_rec": ("PP-OCRv6_tiny_det", "PP-OCRv6_medium_rec"),
}
WORD_RE = re.compile(r"\d+(?:[.,:/-]\d+)*|[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)
NUMBER_RE = re.compile(r"(?<!\w)[+-]?(?:\d[\d\s.,:/\-]*\d|\d)(?!\w)")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_key(value: str) -> str:
    return _sha256_text(value)


def canonical_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u00ad", "").replace("–", "-").replace("—", "-").replace("−", "-")
    return " ".join(text.casefold().split())


def word_tokens(value: str) -> list[str]:
    return WORD_RE.findall(canonical_text(value))


def _canonical_number(token: str) -> str:
    value = canonical_text(token).replace(" ", "").strip(".,;:")
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", value):
        value = value.replace(",", "")
    return value


def number_tokens(value: str) -> list[str]:
    return [_canonical_number(match.group(0)) for match in NUMBER_RE.finditer(value)]


def counter_metrics(reference: Sequence[str], prediction: Sequence[str]) -> dict[str, float | int]:
    ref = Counter(reference)
    pred = Counter(prediction)
    true_positive = sum((ref & pred).values())
    reference_count = sum(ref.values())
    prediction_count = sum(pred.values())
    precision = true_positive / prediction_count if prediction_count else float(reference_count == 0)
    recall = true_positive / reference_count if reference_count else float(prediction_count == 0)
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "reference_count": reference_count,
        "prediction_count": prediction_count,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "error": 1.0 - f1,
    }


def select_pages(pages: Sequence[GTPage], target: int = TARGET_PAGES) -> list[GTPage]:
    """Deterministic layout-balanced selection from the existing geometry holdout."""
    groups: dict[str, list[GTPage]] = defaultdict(list)
    for page in pages:
        groups[page.layout].append(page)
    for group in groups.values():
        group.sort(key=lambda page: (_hash_key(page.page_id), page.domain, page.page_id))

    layouts = sorted(groups)
    selected: list[GTPage] = []
    cursor = 0
    while len(selected) < target and any(groups.values()):
        layout = layouts[cursor % len(layouts)]
        cursor += 1
        if groups[layout]:
            selected.append(groups[layout].pop(0))
    if len(selected) != target:
        raise RuntimeError(f"only {len(selected)} eligible pages; need {target}")
    return selected


def reference_text(page: GTPage) -> str:
    return "\n".join(
        block.text for block in sorted(page.blocks, key=lambda block: (block.order, block.block_id))
    )


def _cpu_self() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def _cpu_children() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(usage.ru_utime + usage.ru_stime)


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
    return normalize_text(output), {"wall_seconds": wall, "cpu_seconds": cpu}


def _unwrap_result(result: Any) -> Mapping[str, Any]:
    payload = result.json
    if callable(payload):
        payload = payload()
    if not isinstance(payload, Mapping):
        raise TypeError(f"unexpected result payload type: {type(payload)!r}")
    inner = payload.get("res", payload)
    if not isinstance(inner, Mapping):
        raise TypeError("result payload does not contain a mapping")
    return inner


def make_pipeline(detector: str, recognizer: str) -> tuple[Any, float]:
    from paddleocr import PaddleOCR

    started = time.perf_counter()
    pipeline = PaddleOCR(
        text_detection_model_name=detector,
        text_recognition_model_name=recognizer,
        device="cpu",
        enable_hpi=True,
        cpu_threads=THREAD_BUDGET,
        text_recognition_batch_size=32,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    return pipeline, time.perf_counter() - started


def run_paddle(pipeline: Any, image_array: np.ndarray) -> tuple[str, dict[str, Any]]:
    before_cpu = _cpu_self()
    started = time.perf_counter()
    results = list(pipeline.predict(image_array))
    wall = time.perf_counter() - started
    cpu = max(0.0, _cpu_self() - before_cpu)
    if len(results) != 1:
        raise AssertionError(f"expected one result, observed {len(results)}")
    payload = _unwrap_result(results[0])
    texts = [normalize_text(str(value)) for value in payload.get("rec_texts", [])]
    scores = [float(value) for value in payload.get("rec_scores", [])]
    boxes = [[int(value) for value in row] for row in payload.get("rec_boxes", [])]
    if len(texts) != len(scores) or len(texts) != len(boxes):
        raise AssertionError("Paddle text, score and box denominators differ")
    output = "\n".join(text for text in texts if text)
    return output, {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "line_count": len(texts),
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "boxes": boxes,
        "scores": scores,
    }


def page_metrics(reference: str, prediction: str) -> dict[str, Any]:
    words = counter_metrics(word_tokens(reference), word_tokens(prediction))
    numbers = counter_metrics(number_tokens(reference), number_tokens(prediction))
    reference_word_count = int(words["reference_count"])
    catastrophic_word = reference_word_count >= 20 and float(words["recall"]) < 0.25
    catastrophic_numeric = int(numbers["reference_count"]) > 0 and float(numbers["recall"]) == 0.0
    return {
        "words": words,
        "numbers": numbers,
        "empty_output": not bool(prediction.strip()),
        "catastrophic": catastrophic_word or catastrophic_numeric,
        "catastrophic_word": catastrophic_word,
        "catastrophic_numeric": catastrophic_numeric,
        "prediction_sha256": _sha256_text(prediction),
    }


def _micro_metrics(rows: Sequence[Mapping[str, Any]], engine: str, token_fn: Any) -> dict[str, Any]:
    reference: list[str] = []
    prediction: list[str] = []
    for row in rows:
        reference.extend(token_fn(str(row["reference_text"])))
        prediction.extend(token_fn(str(row["engines"][engine]["text"])))
    return counter_metrics(reference, prediction)


def aggregate(rows: Sequence[Mapping[str, Any]], engine: str) -> dict[str, Any]:
    wall = sum(float(row["engines"][engine]["runtime"]["wall_seconds"]) for row in rows)
    cpu = sum(float(row["engines"][engine]["runtime"]["cpu_seconds"]) for row in rows)
    return {
        "pages": len(rows),
        "total_wall_seconds": wall,
        "mean_wall_seconds_per_page": wall / max(len(rows), 1),
        "pages_per_second": len(rows) / wall if wall > 0 else 0.0,
        "total_cpu_seconds": cpu,
        "mean_cpu_seconds_per_page": cpu / max(len(rows), 1),
        "effective_cpu_parallelism": cpu / wall if wall > 0 else 0.0,
        "word_micro": _micro_metrics(rows, engine, word_tokens),
        "numeric_micro": _micro_metrics(rows, engine, number_tokens),
        "empty_pages": sum(bool(row["engines"][engine]["metrics"]["empty_output"]) for row in rows),
        "catastrophic_pages": sum(bool(row["engines"][engine]["metrics"]["catastrophic"]) for row in rows),
        "mean_page_word_f1": sum(float(row["engines"][engine]["metrics"]["words"]["f1"]) for row in rows) / max(len(rows), 1),
        "mean_page_numeric_f1": sum(float(row["engines"][engine]["metrics"]["numbers"]["f1"]) for row in rows) / max(len(rows), 1),
    }


def _error_factor(baseline_error: float, candidate_error: float) -> float | None:
    if candidate_error <= 1e-15:
        return None
    return baseline_error / candidate_error


def candidate_gate(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    baseline_word_error = float(baseline["word_micro"]["error"])
    candidate_word_error = float(candidate["word_micro"]["error"])
    baseline_numeric_error = float(baseline["numeric_micro"]["error"])
    candidate_numeric_error = float(candidate["numeric_micro"]["error"])
    speedup = float(baseline["total_wall_seconds"]) / max(float(candidate["total_wall_seconds"]), 1e-15)
    word_10x = candidate_word_error <= baseline_word_error / 10.0 + 1e-15
    numeric_10x = candidate_numeric_error <= baseline_numeric_error / 10.0 + 1e-15
    completeness = (
        float(candidate["word_micro"]["recall"]) >= float(baseline["word_micro"]["recall"]) - 1e-15
        and float(candidate["numeric_micro"]["recall"]) >= float(baseline["numeric_micro"]["recall"]) - 1e-15
        and int(candidate["empty_pages"]) <= int(baseline["empty_pages"])
    )
    no_extra_catastrophic = int(candidate["catastrophic_pages"]) <= int(baseline["catastrophic_pages"])
    return {
        "speedup_vs_tesseract": speedup,
        "speed_10x": speedup >= 10.0,
        "word_error_reduction_factor": _error_factor(baseline_word_error, candidate_word_error),
        "numeric_error_reduction_factor": _error_factor(baseline_numeric_error, candidate_numeric_error),
        "word_quality_10x": word_10x,
        "numeric_quality_10x": numeric_10x,
        "completeness_not_worse": completeness,
        "no_extra_catastrophic_pages": no_extra_catastrophic,
        "full_10x_gate": speedup >= 10.0 and word_10x and numeric_10x and completeness and no_extra_catastrophic,
    }


def decide(aggregates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    baseline = aggregates["tesseract"]
    gates = {name: candidate_gate(baseline, aggregate_row) for name, aggregate_row in aggregates.items() if name != "tesseract"}
    passing = sorted(name for name, gate in gates.items() if gate["full_10x_gate"])

    def progress(name: str) -> tuple[float, float, float, str]:
        gate = gates[name]
        word_factor = gate["word_error_reduction_factor"]
        numeric_factor = gate["numeric_error_reduction_factor"]
        word_progress = 1000.0 if word_factor is None else float(word_factor)
        numeric_progress = 1000.0 if numeric_factor is None else float(numeric_factor)
        return (
            min(float(gate["speedup_vs_tesseract"]) / 10.0, word_progress / 10.0, numeric_progress / 10.0),
            float(gate["speedup_vs_tesseract"]),
            float(aggregates[name]["word_micro"]["f1"]),
            name,
        )

    ranked = sorted((progress(name) for name in gates), reverse=True)
    best = ranked[0][3]
    if passing:
        verdict = "PASS_10X_DEVELOPMENT"
        next_experiment = "freeze the lowest-cost passing candidate and open a new untouched holdout"
    elif gates[best]["speed_10x"]:
        verdict = "SPEED_PASS_QUALITY_RESCUE_REQUIRED"
        next_experiment = "keep the fast detector and test selective recognizer or numeric-crop rescue on a development split"
    else:
        verdict = "NO_FULL_10X_ROUTE_YET"
        next_experiment = "optimize persistent batching and detection resolution before any training"
    return {
        "verdict": verdict,
        "passing_candidates": passing,
        "best_progress_candidate": best,
        "gates": gates,
        "next_experiment": next_experiment,
        "automatic_production_change": False,
    }


def resolve_annotation() -> Path:
    from huggingface_hub import hf_hub_download

    path = Path(hf_hub_download(DATASET_ID, ANNOTATION_FILE, repo_type="dataset", revision=PINNED_REVISION))
    digest = sha256_file(path)
    if digest != EXPECTED_ANNOTATION_SHA256:
        raise RuntimeError(f"annotation hash mismatch: {digest}")
    return path


def build_report(output_dir: Path) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download

    annotation_path = resolve_annotation()
    raw = json.loads(annotation_path.read_text(encoding="utf-8"))
    eligible = [page for item in raw if (page := page_from_raw(item)) is not None]
    selected = select_pages(eligible)

    pipelines: dict[str, Any] = {}
    initialization: dict[str, float] = {}
    for name, (detector, recognizer) in MODEL_SPECS.items():
        pipelines[name], initialization[name] = make_pipeline(detector, recognizer)

    # Warm every pipeline once on a deterministic generated array. Warm-up is not
    # included in page timing and cannot satisfy the primary gate.
    warmup = np.full((256, 1024, 3), 255, dtype=np.uint8)
    for pipeline in pipelines.values():
        list(pipeline.predict(warmup))

    rows: list[dict[str, Any]] = []
    for page in selected:
        dataset_path = page.page_id if page.page_id.startswith("images/") else f"images/{page.page_id}"
        image_path = Path(hf_hub_download(DATASET_ID, dataset_path, repo_type="dataset", revision=PINNED_REVISION))
        image = Image.open(image_path).convert("RGB")
        image_array = np.asarray(image)
        reference = reference_text(page)

        tesseract_text, tesseract_runtime = run_tesseract(image)
        engines: dict[str, Any] = {
            "tesseract": {
                "text": tesseract_text,
                "runtime": tesseract_runtime,
                "metrics": page_metrics(reference, tesseract_text),
            }
        }
        for name, pipeline in pipelines.items():
            text, runtime = run_paddle(pipeline, image_array)
            engines[name] = {
                "text": text,
                "runtime": runtime,
                "metrics": page_metrics(reference, text),
            }
        rows.append(
            {
                "page_id": page.page_id,
                "layout": page.layout,
                "domain": page.domain,
                "image_sha256": sha256_file(image_path),
                "image_bytes": image_path.stat().st_size,
                "reference_text": reference,
                "reference_sha256": _sha256_text(reference),
                "engines": engines,
            }
        )

    engine_names = ["tesseract", *MODEL_SPECS]
    aggregates = {name: aggregate(rows, name) for name in engine_names}
    decision = decide(aggregates)
    stable_payload: dict[str, Any] = {
        "schema": SCHEMA,
        "dataset": {
            "id": DATASET_ID,
            "revision": PINNED_REVISION,
            "annotation_sha256": EXPECTED_ANNOTATION_SHA256,
            "role": "development; pages derive from the previously defined geometry holdout",
            "selection": "layout round-robin over English holdout pages; deterministic SHA-256 ordering; 20 unique pages",
            "selected_page_ids": [page.page_id for page in selected],
            "selected_page_ids_sha256": sha256_bytes(canonical_json([page.page_id for page in selected]).encode("utf-8")),
        },
        "thread_budget": THREAD_BUDGET,
        "model_specs": {name: {"detector": spec[0], "recognizer": spec[1]} for name, spec in MODEL_SPECS.items()},
        "initialization_seconds": initialization,
        "observations": rows,
        "aggregate": aggregates,
        "decision": decision,
        "primary_gate": {
            "same_unique_raster_pages": True,
            "same_runner": True,
            "initialization_excluded_from_page_throughput": True,
            "native_text_counted": False,
            "cache_hits_counted": False,
            "repeated_pages_counted": False,
            "paid_api_used": False,
            "gpu_used": False,
            "gcloud_used": False,
            "speed_requirement": "candidate total wall time <= Tesseract total wall time / 10",
            "word_quality_requirement": "candidate (1-word_F1) <= Tesseract (1-word_F1) / 10",
            "numeric_quality_requirement": "candidate (1-numeric_F1) <= Tesseract (1-numeric_F1) / 10",
        },
    }
    stable_payload["stable_payload_sha256"] = _sha256_text(canonical_json(stable_payload))
    stable_payload["environment"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tesseract": subprocess.check_output(["tesseract", "--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0],
    }
    return stable_payload


def write_report(report: Mapping[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "real_benchmark.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "real_benchmark.sha256").write_text(f"{sha256_file(path)}  real_benchmark.json\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_god_10x_v2/run/benchmark"))
    args = parser.parse_args()
    report = build_report(args.output_dir)
    path = write_report(report, args.output_dir)
    print(json.dumps({
        "report": str(path),
        "aggregate": report["aggregate"],
        "decision": report["decision"],
        "initialization_seconds": report["initialization_seconds"],
        "stable_payload_sha256": report["stable_payload_sha256"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
