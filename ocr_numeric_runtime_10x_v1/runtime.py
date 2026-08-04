"""Runtime numeric proof channel: one Tesseract pass plus batched crop recognition.

The full page is OCRed exactly once by Tesseract. Tesseract's TSV output supplies
both the ordinary text and word boxes. Only numeric tokens repeated on the same
page are cropped. One persistent PP-OCRv6 tiny recognizer processes those crops
in stable batches; no second detector or full-page OCR is executed.

Logic Power is a development-time planner only and is absent from this runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import resource
import subprocess
import time
from collections import Counter, defaultdict
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
    MIN_REPEAT,
    accepted_counter,
    multiset_metrics,
)

SCHEMA = "ocr-numeric-runtime-10x/benchmark/1"
DATASET_ID = "opendatalab/OmniDocBench"
DATASET_REVISION = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"
ANNOTATION_SHA256 = "a45cd84b04ad8b793e775089640e6b681209abea33ead54c1828ddca35fae496"
THREAD_BUDGET = 10
RECOGNITION_BATCH = 16
MAX_OVERHEAD_SECONDS_PER_PAGE = 0.30
MAX_OVERHEAD_RATIO = 0.12
MIN_BASELINE_PARITY_F1 = 0.97
LOO_MIN_ACCEPTED = 250


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
        raise TypeError(f"unexpected OCR result payload: {type(payload)!r}")
    inner = payload.get("res", payload)
    if not isinstance(inner, Mapping):
        raise TypeError("OCR result does not contain a mapping")
    return inner


def parse_recognition_result(result: Any) -> tuple[str, float]:
    payload = _unwrap(result)
    text = normalize_text(str(payload.get("rec_text") or ""))
    score = float(payload.get("rec_score") or 0.0)
    return text, score


def clamp_box(
    box: tuple[int, int, int, int],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    left = max(0, min(left, max(width - 1, 0)))
    top = max(0, min(top, max(height - 1, 0)))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    return left, top, right, bottom


def crop_sha256(crop: Image.Image) -> str:
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG", optimize=False)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def reconstruct_tesseract_page(
    image: Image.Image,
    page_id: str,
) -> dict[str, Any]:
    """Run Tesseract once and recover ordered text plus numeric word boxes."""
    os.environ["OMP_THREAD_LIMIT"] = str(THREAD_BUDGET)
    before_cpu = _cpu_children()
    started = time.perf_counter()
    data = pytesseract.image_to_data(
        image,
        lang="eng",
        config="--oem 1 --psm 3",
        output_type=pytesseract.Output.DICT,
    )
    wall = time.perf_counter() - started
    cpu = max(0.0, _cpu_children() - before_cpu)

    required = {
        "text",
        "conf",
        "left",
        "top",
        "width",
        "height",
        "block_num",
        "par_num",
        "line_num",
    }
    missing = sorted(required - set(data))
    if missing:
        raise RuntimeError(f"Tesseract TSV missing fields: {missing}")
    denominator = len(data["text"])
    if any(len(data[field]) != denominator for field in required):
        raise RuntimeError("Tesseract TSV field denominators differ")

    lines: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    line_first_index: dict[tuple[int, int, int], int] = {}
    candidates: list[dict[str, Any]] = []
    for index, raw_text in enumerate(data["text"]):
        text = normalize_text(str(raw_text))
        if not text:
            continue
        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        line_first_index.setdefault(key, index)
        left = int(data["left"][index])
        top = int(data["top"][index])
        width = int(data["width"][index])
        height = int(data["height"][index])
        try:
            confidence = max(0.0, min(1.0, float(data["conf"][index]) / 100.0))
        except (TypeError, ValueError):
            confidence = 0.0
        item = {
            "index": index,
            "text": text,
            "confidence": confidence,
            "box": [left, top, left + width, top + height],
        }
        lines[key].append(item)

        tokens = number_tokens(text)
        if len(tokens) != 1:
            continue
        margin = max(3, round(height * 0.20))
        box = clamp_box(
            (
                left - margin,
                top - margin,
                left + width + margin,
                top + height + margin,
            ),
            image.width,
            image.height,
        )
        candidates.append(
            {
                "candidate_id": (
                    hashlib.sha256(page_id.encode("utf-8")).hexdigest()[:12]
                    + f"-{index:05d}"
                ),
                "page_id": page_id,
                "word_index": index,
                "baseline_token": tokens[0],
                "tesseract_text": text,
                "tesseract_confidence": confidence,
                "bbox": list(box),
            }
        )

    ordered_keys = sorted(lines, key=lambda key: line_first_index[key])
    text = "\n".join(
        " ".join(item["text"] for item in sorted(lines[key], key=lambda item: item["index"]))
        for key in ordered_keys
    )
    baseline_tokens = number_tokens(text)
    candidate_counts = Counter(item["baseline_token"] for item in candidates)
    repeated = [
        item
        for item in candidates
        if candidate_counts[item["baseline_token"]] >= MIN_REPEAT
    ]
    return {
        "text": text,
        "baseline_tokens": baseline_tokens,
        "numeric_candidates": candidates,
        "repeated_candidates": repeated,
        "candidate_counts": dict(sorted(candidate_counts.items())),
        "runtime": {
            "wall_seconds": wall,
            "cpu_seconds": cpu,
        },
        "word_count": sum(len(lines[key]) for key in ordered_keys),
    }


def make_recognizer() -> tuple[Any, dict[str, float]]:
    from paddleocr import TextRecognition

    started = time.perf_counter()
    recognizer = TextRecognition(
        model_name="PP-OCRv6_tiny_rec",
        device="cpu",
        enable_hpi=True,
        cpu_threads=THREAD_BUDGET,
    )
    initialized = time.perf_counter()
    blank = np.full((48, 320, 3), 255, dtype=np.uint8)
    list(recognizer.predict(input=[blank], batch_size=1))
    warmed = time.perf_counter()
    return recognizer, {
        "model_initialization_seconds": initialized - started,
        "warmup_seconds": warmed - initialized,
    }


def recognize_crops(
    recognizer: Any,
    crops: Sequence[np.ndarray],
) -> tuple[list[tuple[str, float]], dict[str, float]]:
    if not crops:
        return [], {"wall_seconds": 0.0, "cpu_seconds": 0.0}
    before_cpu = _cpu_self()
    started = time.perf_counter()
    outputs = list(
        recognizer.predict(input=list(crops), batch_size=RECOGNITION_BATCH)
    )
    wall = time.perf_counter() - started
    cpu = max(0.0, _cpu_self() - before_cpu)
    if len(outputs) != len(crops):
        raise RuntimeError(
            f"recognition denominator mismatch: {len(outputs)} != {len(crops)}"
        )
    return [parse_recognition_result(output) for output in outputs], {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
    }


def accepted_from_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    min_repeat: int = MIN_REPEAT,
) -> Counter[str]:
    """Accept only repeated per-page tokens with at least two crop agreements."""
    baseline = Counter(str(item["baseline_token"]) for item in candidates)
    agreement = Counter(
        str(item["baseline_token"])
        for item in candidates
        if item.get("paddle_token") == item.get("baseline_token")
    )
    accepted: Counter[str] = Counter()
    for token in sorted(baseline.keys() & agreement.keys()):
        if baseline[token] >= min_repeat and agreement[token] >= min_repeat:
            accepted[token] = min(baseline[token], agreement[token])
    return +accepted


def _aggregate_counters(
    pages: Sequence[Mapping[str, Any]],
) -> tuple[Counter[str], Counter[str], Counter[str]]:
    reference: Counter[str] = Counter()
    baseline: Counter[str] = Counter()
    accepted: Counter[str] = Counter()
    for page in pages:
        reference.update(str(value) for value in page["reference_tokens"])
        baseline.update(str(value) for value in page["baseline_tokens"])
        accepted.update(str(value) for value in page["accepted_tokens"])
    return reference, baseline, accepted


def evaluate_pages(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reference, baseline, accepted = _aggregate_counters(pages)
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


def counter_parity(
    observed: Counter[str],
    frozen: Counter[str],
) -> dict[str, Any]:
    metrics = multiset_metrics(frozen, observed)
    return {
        "f1": metrics["f1"],
        "precision": metrics["precision"],
        "reference_coverage": metrics["reference_coverage"],
        "observed_count": metrics["prediction_count"],
        "frozen_count": metrics["reference_count"],
        "matching_count": metrics["true_positive"],
    }


def stable_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"environment", "stable_payload_sha256"}
    }


def build_report(
    quality_report_path: Path,
    artifact_sha256: str,
) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download

    quality = json.loads(quality_report_path.read_text(encoding="utf-8"))
    observations = quality.get("observations") or []
    if len(observations) != 20:
        raise RuntimeError(f"expected 20 frozen pages, observed {len(observations)}")
    page_ids = [str(item["page_id"]) for item in observations]
    if len(set(page_ids)) != len(page_ids):
        raise RuntimeError("duplicate frozen page identities")

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

    frozen_by_page = {str(item["page_id"]): item for item in observations}
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
        image = Image.open(image_path).convert("RGB")
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

    page_runtime: dict[str, dict[str, Any]] = {}
    tesseract_wall = 0.0
    tesseract_cpu = 0.0
    for page_id in page_ids:
        result = reconstruct_tesseract_page(images[page_id], page_id)
        page_runtime[page_id] = result
        tesseract_wall += float(result["runtime"]["wall_seconds"])
        tesseract_cpu += float(result["runtime"]["cpu_seconds"])

    crop_started = time.perf_counter()
    crop_cpu_started = _cpu_self()
    crop_arrays: list[np.ndarray] = []
    crop_candidates: list[dict[str, Any]] = []
    for page_id in page_ids:
        image = images[page_id]
        for source in page_runtime[page_id]["repeated_candidates"]:
            candidate = dict(source)
            box = tuple(int(value) for value in candidate["bbox"])
            crop = image.crop(box)
            if crop.width < 2 or crop.height < 2:
                raise RuntimeError("empty numeric crop")
            candidate["crop_sha256"] = crop_sha256(crop)
            candidate["crop_width"] = crop.width
            candidate["crop_height"] = crop.height
            crop_candidates.append(candidate)
            crop_arrays.append(np.asarray(crop, dtype=np.uint8))
    crop_wall = time.perf_counter() - crop_started
    crop_cpu = max(0.0, _cpu_self() - crop_cpu_started)

    recognizer, initialization = make_recognizer()
    recognized, recognition_runtime = recognize_crops(recognizer, crop_arrays)
    for candidate, (text, score) in zip(crop_candidates, recognized, strict=True):
        tokens = number_tokens(text)
        candidate["paddle_text"] = text
        candidate["paddle_token"] = tokens[0] if len(tokens) == 1 else None
        candidate["paddle_token_count"] = len(tokens)
        candidate["paddle_confidence"] = score
        candidate["agrees"] = candidate["paddle_token"] == candidate["baseline_token"]

    candidates_by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in crop_candidates:
        candidates_by_page[candidate["page_id"]].append(candidate)

    pages: list[dict[str, Any]] = []
    frozen_baseline_all: Counter[str] = Counter()
    runtime_baseline_all: Counter[str] = Counter()
    frozen_accepted_all: Counter[str] = Counter()
    runtime_accepted_all: Counter[str] = Counter()
    for page_id in page_ids:
        frozen = frozen_by_page[page_id]
        runtime = page_runtime[page_id]
        reference_tokens = number_tokens(str(frozen["reference"]["full"]))
        frozen_tesseract = number_tokens(str(frozen["engines"]["tesseract"]))
        frozen_paddle = number_tokens(str(frozen["engines"]["pp_tiny"]))
        frozen_accepted = accepted_counter(
            Counter(frozen_tesseract),
            Counter(frozen_paddle),
        )
        candidates = sorted(
            candidates_by_page.get(page_id, []),
            key=lambda item: int(item["word_index"]),
        )
        runtime_accepted = accepted_from_candidates(candidates)

        frozen_baseline_all.update(frozen_tesseract)
        runtime_baseline_all.update(str(value) for value in runtime["baseline_tokens"])
        frozen_accepted_all.update(frozen_accepted)
        runtime_accepted_all.update(runtime_accepted)
        pages.append(
            {
                "page_id": page_id,
                "reference_tokens": reference_tokens,
                "baseline_tokens": list(runtime["baseline_tokens"]),
                "frozen_baseline_tokens": frozen_tesseract,
                "accepted_tokens": [
                    token
                    for token in sorted(runtime_accepted)
                    for _ in range(runtime_accepted[token])
                ],
                "frozen_accepted_tokens": [
                    token
                    for token in sorted(frozen_accepted)
                    for _ in range(frozen_accepted[token])
                ],
                "ordinary_numeric_candidate_count": len(runtime["numeric_candidates"]),
                "repeated_candidate_count": len(candidates),
                "accepted_count": sum(runtime_accepted.values()),
                "candidate_counts": runtime["candidate_counts"],
                "tesseract_runtime": runtime["runtime"],
                "candidates": candidates,
            }
        )

    evaluation = evaluate_pages(pages)
    loo = loo_diagnostics(pages)
    baseline_parity = counter_parity(runtime_baseline_all, frozen_baseline_all)
    accepted_parity = counter_parity(runtime_accepted_all, frozen_accepted_all)
    page_count = max(len(pages), 1)
    overhead_wall = crop_wall + float(recognition_runtime["wall_seconds"])
    overhead_cpu = crop_cpu + float(recognition_runtime["cpu_seconds"])
    overhead_per_page = overhead_wall / page_count
    overhead_ratio = overhead_wall / max(tesseract_wall, 1e-15)

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
        float(baseline_parity["f1"]) >= MIN_BASELINE_PARITY_F1
        and overhead_per_page <= MAX_OVERHEAD_SECONDS_PER_PAGE
        and overhead_ratio <= MAX_OVERHEAD_RATIO
        and len(recognized) == len(crop_candidates)
    )
    promotion_gate = quality_gate and runtime_gate
    verdict = (
        "PASS_RUNTIME_NUMERIC_PROOF_10X"
        if promotion_gate
        else (
            "QUALITY_PASS_RUNTIME_GATE_FAILED"
            if quality_gate
            else "RUNTIME_NUMERIC_PROOF_GATE_FAILED"
        )
    )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "quality_report_sha256": sha256_file(quality_report_path),
            "quality_stable_payload_sha256": quality["stable_payload_sha256"],
            "quality_artifact_sha256": artifact_sha256,
            "dataset_id": DATASET_ID,
            "dataset_revision": DATASET_REVISION,
            "annotation_sha256": ANNOTATION_SHA256,
        },
        "runtime_contract": {
            "full_page_ocr_passes": 1,
            "full_page_engine": "Tesseract 5.3.4 compatible",
            "tesseract_configuration": "--oem 1 --psm 3 -l eng",
            "box_source": "same Tesseract TSV pass",
            "second_detector": False,
            "crop_recognizer": "PP-OCRv6_tiny_rec",
            "recognition_batch": RECOGNITION_BATCH,
            "minimum_repetitions_per_page": MIN_REPEAT,
            "acceptance": (
                "same canonical token in Tesseract crop source and PP crop "
                "recognition, with at least two agreements per page"
            ),
            "all_other_numbers": "ABSTAIN_FROM_EVIDENCE_PROMOTION",
        },
        "gates": {
            "minimum_false_acceptance_error_reduction": MIN_ERROR_REDUCTION,
            "minimum_precision": MIN_PRECISION,
            "minimum_reference_coverage": MIN_REFERENCE_COVERAGE,
            "minimum_accepted_count": MIN_ACCEPTED,
            "minimum_leave_one_page_out_passes": MIN_LOO_PASSES,
            "minimum_baseline_parity_f1": MIN_BASELINE_PARITY_F1,
            "maximum_overhead_seconds_per_page": MAX_OVERHEAD_SECONDS_PER_PAGE,
            "maximum_overhead_ratio": MAX_OVERHEAD_RATIO,
        },
        "image_manifest": image_manifest,
        "pages": pages,
        "evaluation": evaluation,
        "leave_one_page_out": loo,
        "parity": {
            "runtime_vs_frozen_tesseract": baseline_parity,
            "runtime_vs_frozen_accepted_channel": accepted_parity,
        },
        "runtime": {
            "tesseract": {
                "total_wall_seconds": tesseract_wall,
                "mean_wall_seconds_per_page": tesseract_wall / page_count,
                "total_cpu_seconds": tesseract_cpu,
            },
            "crop_construction": {
                "total_wall_seconds": crop_wall,
                "total_cpu_seconds": crop_cpu,
            },
            "recognition": {
                **recognition_runtime,
                "crops": len(crop_candidates),
                "mean_wall_seconds_per_crop": (
                    float(recognition_runtime["wall_seconds"])
                    / max(len(crop_candidates), 1)
                ),
            },
            "initialization_excluded_from_steady_state": initialization,
            "incremental_overhead": {
                "total_wall_seconds": overhead_wall,
                "mean_wall_seconds_per_page": overhead_per_page,
                "ratio_to_tesseract": overhead_ratio,
                "total_cpu_seconds": overhead_cpu,
            },
        },
        "decision": {
            "verdict": verdict,
            "quality_gate": quality_gate,
            "runtime_gate": runtime_gate,
            "promotion_gate": promotion_gate,
            "automatic_production_change": False,
            "next_experiment": (
                "open a new untouched Honduran numeric holdout"
                if promotion_gate
                else "inspect failed gate without retuning on these pages"
            ),
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "logic_power_in_runtime": False,
            "native_text_counted_as_raster_speed": False,
            "cache_hits_counted_as_raster_speed": False,
        },
    }
    payload["stable_payload_sha256"] = sha256_bytes(
        canonical_json(stable_payload(payload)).encode("utf-8")
    )
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
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_numeric_runtime_10x_v1/run"),
    )
    args = parser.parse_args()
    report = build_report(args.quality_report, args.artifact_sha256)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "numeric_runtime_benchmark.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "numeric_runtime_benchmark.sha256").write_text(
        f"{sha256_file(path)}  numeric_runtime_benchmark.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(path),
                "evaluation": report["evaluation"],
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
