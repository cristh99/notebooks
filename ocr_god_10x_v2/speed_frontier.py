"""Frozen PP-OCRv6 tiny resolution frontier on the same real pages."""
from __future__ import annotations

import argparse
import json
import platform
import resource
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

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
    _unwrap_result,
    aggregate,
    make_pipeline,
    page_metrics,
    reference_text,
    run_tesseract,
    select_pages,
)

SCHEMA = "ocr-god-10x/speed-frontier/1"
LIMITS = (4000, 2048, 1536, 1280, 1024, 768, 640, 512)


def _cpu_self() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def run_limited(pipeline: Any, image_array: np.ndarray, limit: int) -> tuple[str, dict[str, Any]]:
    before_cpu = _cpu_self()
    started = time.perf_counter()
    results = list(
        pipeline.predict(
            image_array,
            text_det_limit_side_len=limit,
            text_det_limit_type="max",
        )
    )
    wall = time.perf_counter() - started
    cpu = max(0.0, _cpu_self() - before_cpu)
    if len(results) != 1:
        raise AssertionError(f"expected one result, observed {len(results)}")
    payload = _unwrap_result(results[0])
    texts = [" ".join(str(value).split()) for value in payload.get("rec_texts", [])]
    scores = [float(value) for value in payload.get("rec_scores", [])]
    boxes = [[int(value) for value in row] for row in payload.get("rec_boxes", [])]
    if len(texts) != len(scores) or len(texts) != len(boxes):
        raise AssertionError("text, score and box denominators differ")
    output = "\n".join(text for text in texts if text)
    return output, {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "line_count": len(texts),
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "scores": scores,
        "boxes": boxes,
    }


def fidelity_gate(default: Mapping[str, Any], baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    speedup = float(baseline["total_wall_seconds"]) / max(float(candidate["total_wall_seconds"]), 1e-15)
    cpu_speedup = float(baseline["total_cpu_seconds"]) / max(float(candidate["total_cpu_seconds"]), 1e-15)
    default_word = float(default["word_micro"]["f1"])
    default_numeric = float(default["numeric_micro"]["f1"])
    word_loss = default_word - float(candidate["word_micro"]["f1"])
    numeric_loss = default_numeric - float(candidate["numeric_micro"]["f1"])
    preserves_tiny = (
        word_loss <= 0.005 + 1e-15
        and numeric_loss <= 0.005 + 1e-15
        and int(candidate["catastrophic_pages"]) <= int(default["catastrophic_pages"])
        and int(candidate["empty_pages"]) <= int(default["empty_pages"])
    )
    preserves_tesseract = (
        float(candidate["word_micro"]["f1"]) >= float(baseline["word_micro"]["f1"]) - 0.01
        and float(candidate["numeric_micro"]["f1"]) >= float(baseline["numeric_micro"]["f1"]) - 0.01
        and int(candidate["catastrophic_pages"]) <= int(baseline["catastrophic_pages"])
    )
    return {
        "wall_speedup_vs_tesseract": speedup,
        "cpu_speedup_vs_tesseract": cpu_speedup,
        "wall_speed_10x": speedup >= 10.0,
        "cpu_speed_10x": cpu_speedup >= 10.0,
        "word_f1_loss_vs_full_tiny": word_loss,
        "numeric_f1_loss_vs_full_tiny": numeric_loss,
        "preserves_full_tiny_within_0_5pp": preserves_tiny,
        "within_1pp_of_tesseract_word_and_numeric": preserves_tesseract,
        "speed_and_full_tiny_fidelity_gate": speedup >= 10.0 and preserves_tiny,
        "speed_and_tesseract_fidelity_gate": speedup >= 10.0 and preserves_tesseract,
    }


def build_report() -> dict[str, Any]:
    from huggingface_hub import hf_hub_download

    annotation = Path(hf_hub_download(DATASET_ID, ANNOTATION_FILE, repo_type="dataset", revision=PINNED_REVISION))
    if sha256_file(annotation) != EXPECTED_ANNOTATION_SHA256:
        raise RuntimeError("annotation hash mismatch")
    raw = json.loads(annotation.read_text(encoding="utf-8"))
    eligible = [page for item in raw if (page := page_from_raw(item)) is not None]
    selected = select_pages(eligible)

    pipeline, initialization_seconds = make_pipeline("PP-OCRv6_tiny_det", "PP-OCRv6_tiny_rec")
    list(pipeline.predict(np.full((256, 1024, 3), 255, dtype=np.uint8)))

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
        for limit in LIMITS:
            name = f"max_{limit}"
            text, runtime = run_limited(pipeline, image_array, limit)
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
                "image_width": image.width,
                "image_height": image.height,
                "reference_text": reference,
                "reference_sha256": _sha256_text(reference),
                "engines": engines,
            }
        )

    engine_names = ["tesseract", *(f"max_{limit}" for limit in LIMITS)]
    aggregates = {name: aggregate(rows, name) for name in engine_names}
    baseline = aggregates["tesseract"]
    default = aggregates["max_4000"]
    gates = {
        f"max_{limit}": fidelity_gate(default, baseline, aggregates[f"max_{limit}"])
        for limit in LIMITS
    }
    fidelity_candidates = [
        (float(aggregates[name]["total_wall_seconds"]), name)
        for name, gate in gates.items()
        if gate["preserves_full_tiny_within_0_5pp"]
    ]
    selected_name = min(fidelity_candidates)[1] if fidelity_candidates else "max_4000"
    strict_passing = sorted(name for name, gate in gates.items() if gate["speed_and_tesseract_fidelity_gate"])
    if strict_passing:
        verdict = "RAW_SPEED_10X_WITH_TESSERACT_FIDELITY"
        next_experiment = "freeze the fastest strict candidate and open an untouched holdout"
    elif gates[selected_name]["wall_speed_10x"]:
        verdict = "SPEED_10X_ONLY_QUALITY_RESCUE_REQUIRED"
        next_experiment = "freeze the speed candidate as detector tier and add evidence-aware numeric and word rescue"
    else:
        verdict = "RAW_SPEED_10X_NOT_REACHED"
        next_experiment = "test multi-page batching and direct module inference before changing models"

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "dataset": {
            "id": DATASET_ID,
            "revision": PINNED_REVISION,
            "annotation_sha256": EXPECTED_ANNOTATION_SHA256,
            "role": "development",
            "selection": "same deterministic 20-page layout round-robin used by Stage 1",
            "selected_page_ids": [page.page_id for page in selected],
            "selected_page_ids_sha256": sha256_bytes(canonical_json([page.page_id for page in selected]).encode("utf-8")),
        },
        "thread_budget": THREAD_BUDGET,
        "limits": list(LIMITS),
        "initialization_seconds": initialization_seconds,
        "observations": rows,
        "aggregate": aggregates,
        "decision": {
            "verdict": verdict,
            "selected_fidelity_candidate": selected_name,
            "strict_passing_candidates": strict_passing,
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
        "tesseract": subprocess.check_output(["tesseract", "--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_god_10x_v2/run/speed_frontier"))
    args = parser.parse_args()
    report = build_report()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "speed_frontier.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "speed_frontier.sha256").write_text(f"{sha256_file(path)}  speed_frontier.json\n", encoding="utf-8")
    print(json.dumps({
        "report": str(path),
        "decision": report["decision"],
        "aggregate": report["aggregate"],
        "stable_payload_sha256": report["stable_payload_sha256"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
