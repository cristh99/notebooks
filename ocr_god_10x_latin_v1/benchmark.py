"""Same-runner benchmark for the Latin PP-OCRv5 mobile recognizer.

The detector is the already-viable PP-OCRv6 tiny detector. The recognizer is
frozen as latin_PP-OCRv5_mobile_rec. Four detection limits are evaluated on
the exact 20 Stage 1 page identities using the repaired full-content metric.
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
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image
import pytesseract

from ocr_god_10x_quality_v1.full_content_quality import (
    DATASET_ID,
    PINNED_REVISION,
    annotation_map,
    canonical_json,
    counter_metrics,
    number_tokens,
    page_reference,
    sha256_bytes,
    sha256_file,
    word_tokens,
)

SCHEMA = "ocr-god-10x/latin-benchmark/1"
LIMITS = (1536, 1024, 768, 512)
THREADS = 10
MODEL = "latin_PP-OCRv5_mobile_rec"
DETECTOR = "PP-OCRv6_tiny_det"


def cpu_self() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def cpu_children() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(usage.ru_utime + usage.ru_stime)


def normalize_output(value: str) -> str:
    return "\n".join(" ".join(line.split()) for line in value.splitlines() if line.split())


def unwrap(result: Any) -> Mapping[str, Any]:
    payload = result.json
    if callable(payload):
        payload = payload()
    if not isinstance(payload, Mapping):
        raise TypeError(f"unexpected result payload type: {type(payload)!r}")
    inner = payload.get("res", payload)
    if not isinstance(inner, Mapping):
        raise TypeError("result payload does not contain a mapping")
    return inner


def run_tesseract(image: Image.Image) -> tuple[str, dict[str, float]]:
    os.environ["OMP_THREAD_LIMIT"] = str(THREADS)
    before = cpu_children()
    started = time.perf_counter()
    text = pytesseract.image_to_string(
        image,
        lang="eng",
        config="--oem 1 --psm 3",
    )
    wall = time.perf_counter() - started
    return normalize_output(text), {
        "wall_seconds": wall,
        "cpu_seconds": max(0.0, cpu_children() - before),
    }


def run_paddle(
    pipeline: Any,
    image: np.ndarray,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    before = cpu_self()
    started = time.perf_counter()
    results = list(
        pipeline.predict(
            image,
            text_det_limit_side_len=limit,
            text_det_limit_type="max",
        )
    )
    wall = time.perf_counter() - started
    if len(results) != 1:
        raise AssertionError(f"expected one result, observed {len(results)}")
    payload = unwrap(results[0])
    texts = [normalize_output(str(value)) for value in payload.get("rec_texts", [])]
    scores = [float(value) for value in payload.get("rec_scores", [])]
    boxes = [[int(value) for value in row] for row in payload.get("rec_boxes", [])]
    if len(texts) != len(scores) or len(texts) != len(boxes):
        raise AssertionError("text, score and box denominators differ")
    return "\n".join(value for value in texts if value), {
        "wall_seconds": wall,
        "cpu_seconds": max(0.0, cpu_self() - before),
        "line_count": len(texts),
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "scores": scores,
        "boxes": boxes,
    }


def page_metrics(reference: Mapping[str, Any], prediction: str) -> dict[str, Any]:
    word = counter_metrics(word_tokens(str(reference["full"])), word_tokens(prediction))
    numeric = counter_metrics(number_tokens(str(reference["full"])), number_tokens(prediction))
    table = counter_metrics(word_tokens(str(reference["table"])), word_tokens(prediction))
    formula = counter_metrics(word_tokens(str(reference["formula"])), word_tokens(prediction))
    catastrophic_word = int(word["reference_count"]) >= 20 and float(word["recall"]) < 0.25
    catastrophic_numeric = int(numeric["reference_count"]) > 0 and float(numeric["recall"]) == 0.0
    return {
        "word": word,
        "numeric": numeric,
        "table_word_recall": table["recall"],
        "formula_word_recall": formula["recall"],
        "empty_output": not bool(prediction.strip()),
        "catastrophic": catastrophic_word or catastrophic_numeric,
        "prediction_sha256": sha256_bytes(prediction.encode("utf-8")),
    }


def micro(rows: Sequence[Mapping[str, Any]], engine: str, reference_key: str, token_fn: Any) -> dict[str, Any]:
    reference: list[str] = []
    prediction: list[str] = []
    for row in rows:
        reference.extend(token_fn(str(row["reference"][reference_key])))
        prediction.extend(token_fn(str(row["engines"][engine]["text"])))
    return counter_metrics(reference, prediction)


def aggregate(rows: Sequence[Mapping[str, Any]], engine: str) -> dict[str, Any]:
    wall = sum(float(row["engines"][engine]["runtime"]["wall_seconds"]) for row in rows)
    cpu = sum(float(row["engines"][engine]["runtime"]["cpu_seconds"]) for row in rows)
    return {
        "pages": len(rows),
        "total_wall_seconds": wall,
        "mean_wall_seconds_per_page": wall / max(1, len(rows)),
        "pages_per_second": len(rows) / wall if wall else 0.0,
        "total_cpu_seconds": cpu,
        "mean_cpu_seconds_per_page": cpu / max(1, len(rows)),
        "effective_cpu_parallelism": cpu / wall if wall else 0.0,
        "full_word": micro(rows, engine, "full", word_tokens),
        "full_numeric": micro(rows, engine, "full", number_tokens),
        "table_word_recall": micro(rows, engine, "table", word_tokens)["recall"],
        "formula_word_recall": micro(rows, engine, "formula", word_tokens)["recall"],
        "empty_pages": sum(bool(row["engines"][engine]["metrics"]["empty_output"]) for row in rows),
        "catastrophic_pages": sum(bool(row["engines"][engine]["metrics"]["catastrophic"]) for row in rows),
    }


def gate(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    speedup = float(baseline["total_wall_seconds"]) / max(float(candidate["total_wall_seconds"]), 1e-15)
    word_error = float(candidate["full_word"]["error"])
    numeric_error = float(candidate["full_numeric"]["error"])
    baseline_word_error = float(baseline["full_word"]["error"])
    baseline_numeric_error = float(baseline["full_numeric"]["error"])
    word_10x = word_error <= baseline_word_error / 10.0 + 1e-15
    numeric_10x = numeric_error <= baseline_numeric_error / 10.0 + 1e-15
    completeness = (
        float(candidate["full_word"]["recall"]) >= float(baseline["full_word"]["recall"]) - 1e-15
        and float(candidate["full_numeric"]["recall"]) >= float(baseline["full_numeric"]["recall"]) - 1e-15
        and int(candidate["empty_pages"]) <= int(baseline["empty_pages"])
        and int(candidate["catastrophic_pages"]) <= int(baseline["catastrophic_pages"])
    )
    return {
        "wall_speedup_vs_tesseract": speedup,
        "speed_10x": speedup >= 10.0,
        "word_error_reduction_factor": baseline_word_error / word_error if word_error > 1e-15 else None,
        "numeric_error_reduction_factor": baseline_numeric_error / numeric_error if numeric_error > 1e-15 else None,
        "word_quality_10x": word_10x,
        "numeric_quality_10x": numeric_10x,
        "completeness_not_worse": completeness,
        "full_10x_gate": speedup >= 10.0 and word_10x and numeric_10x and completeness,
    }


def build_report(stage1_path: Path, annotation_path: Path, artifact_sha256: str) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download
    from paddleocr import PaddleOCR

    stage1 = json.loads(stage1_path.read_text(encoding="utf-8"))
    page_ids = list(stage1["dataset"]["selected_page_ids"])
    if len(page_ids) != 20 or len(set(page_ids)) != 20:
        raise RuntimeError("Stage 1 page identity denominator changed")
    if sha256_file(annotation_path) != stage1["dataset"]["annotation_sha256"]:
        raise RuntimeError("annotation hash mismatch")
    raw_pages = json.loads(annotation_path.read_text(encoding="utf-8"))
    raw_map = annotation_map(raw_pages)

    init_started = time.perf_counter()
    pipeline = PaddleOCR(
        text_detection_model_name=DETECTOR,
        text_recognition_model_name=MODEL,
        device="cpu",
        enable_hpi=True,
        cpu_threads=THREADS,
        text_recognition_batch_size=32,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    initialization_seconds = time.perf_counter() - init_started
    list(pipeline.predict(np.full((256, 1024, 3), 255, dtype=np.uint8)))

    rows: list[dict[str, Any]] = []
    for page_id in page_ids:
        raw = raw_map.get(page_id) or raw_map.get(Path(page_id).name)
        if raw is None:
            raise KeyError(f"annotation missing: {page_id}")
        reference = page_reference(raw)
        dataset_path = page_id if page_id.startswith("images/") else f"images/{page_id}"
        image_path = Path(hf_hub_download(DATASET_ID, dataset_path, repo_type="dataset", revision=PINNED_REVISION))
        pil_image = Image.open(image_path).convert("RGB")
        array = np.asarray(pil_image)
        tess_text, tess_runtime = run_tesseract(pil_image)
        engines: dict[str, Any] = {
            "tesseract": {
                "text": tess_text,
                "runtime": tess_runtime,
                "metrics": page_metrics(reference, tess_text),
            }
        }
        for limit in LIMITS:
            name = f"latin_{limit}"
            text, runtime = run_paddle(pipeline, array, limit)
            engines[name] = {
                "text": text,
                "runtime": runtime,
                "metrics": page_metrics(reference, text),
            }
        rows.append({
            "page_id": page_id,
            "image_sha256": sha256_file(image_path),
            "image_bytes": image_path.stat().st_size,
            "reference": reference,
            "engines": engines,
        })

    engine_names = ["tesseract", *(f"latin_{limit}" for limit in LIMITS)]
    aggregates = {name: aggregate(rows, name) for name in engine_names}
    baseline = aggregates["tesseract"]
    gates = {name: gate(baseline, aggregates[name]) for name in engine_names if name != "tesseract"}
    passing = sorted(name for name, value in gates.items() if value["full_10x_gate"])
    quality_winner = max(
        gates,
        key=lambda name: (
            float(aggregates[name]["full_word"]["f1"]),
            float(aggregates[name]["full_numeric"]["f1"]),
            -float(aggregates[name]["total_wall_seconds"]),
        ),
    )
    fastest = min(gates, key=lambda name: float(aggregates[name]["total_wall_seconds"]))
    if passing:
        verdict = "LATIN_MODEL_PASS_10X_DEVELOPMENT"
        next_experiment = "freeze the least costly passing configuration and open a new untouched holdout"
    elif any(value["speed_10x"] for value in gates.values()):
        verdict = "LATIN_SPEED_PASS_QUALITY_NOT_10X"
        next_experiment = "preserve the fast Latin tier and add structured numeric/table rescue"
    elif max(float(aggregates[name]["full_word"]["f1"]) for name in gates) > float(baseline["full_word"]["f1"]):
        verdict = "LATIN_QUALITY_GAIN_SPEED_BELOW_10X"
        next_experiment = "combine the quality winner with exact reuse and page-level native routing for system throughput"
    else:
        verdict = "LATIN_MODEL_NO_GO"
        next_experiment = "do not train until error taxonomy identifies a learnable residual"

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "stage1_report_sha256": sha256_file(stage1_path),
            "stage1_artifact_sha256": artifact_sha256,
            "stage1_stable_payload_sha256": stage1["stable_payload_sha256"],
            "dataset_id": DATASET_ID,
            "dataset_revision": PINNED_REVISION,
            "annotation_sha256": stage1["dataset"]["annotation_sha256"],
            "selected_page_ids": page_ids,
            "selected_page_ids_sha256": sha256_bytes(canonical_json(page_ids).encode("utf-8")),
        },
        "model": {
            "detector": DETECTOR,
            "recognizer": MODEL,
            "limits": list(LIMITS),
            "thread_budget": THREADS,
            "initialization_seconds": initialization_seconds,
        },
        "observations": rows,
        "aggregate": aggregates,
        "decision": {
            "verdict": verdict,
            "passing_candidates": passing,
            "quality_winner": quality_winner,
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
    payload["stable_payload_sha256"] = sha256_bytes(canonical_json(payload).encode("utf-8"))
    payload["environment"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tesseract": subprocess.check_output(["tesseract", "--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1-report", type=Path, required=True)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_god_10x_latin_v1/run"))
    args = parser.parse_args()
    report = build_report(args.stage1_report, args.annotation, args.artifact_sha256)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "latin_benchmark.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "latin_benchmark.sha256").write_text(f"{sha256_file(path)}  latin_benchmark.json\n", encoding="utf-8")
    print(json.dumps({
        "report": str(path),
        "aggregate": report["aggregate"],
        "decision": report["decision"],
        "stable_payload_sha256": report["stable_payload_sha256"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
