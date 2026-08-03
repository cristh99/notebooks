from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from huggingface_hub import hf_hub_download
from PIL import Image
import psutil
import pytesseract

from ocr_sota_real_canary_v2 import run_canary as core
from ocr_sota_real_canary_v2 import run_ci_canary as compatibility  # patches current APIs

from .rescue import (
    RescuePolicy,
    align_prediction_to_reference,
    apply_policy,
    digest_payload,
    numeric_tokens,
    sequence_accuracy,
    summarize_candidates,
)
from .verify_report import SCHEMA, stable_payload

DATASET_ID = "opendatalab/OmniDocBench"
DATASET_REVISION = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"
ANNOTATION_FILE = "OmniDocBench.json"
ANNOTATION_SHA256 = "a45cd84b04ad8b793e775089640e6b681209abea33ead54c1828ddca35fae496"
SELECTED_PAGES = (
    "docstructbench_llm-raw-scihub-o.O-s00374-003-0589-2.pdf_6.jpg",
    "PPT_ch7_page_136.png",
    "magazine_TheEconomist.2023.12.23_page_052.png",
    "newspaper_The Times UK_0801@magazinesclubnew_page_020.png",
    "book_en_6.Complex.Analysis.-.Elias.M..Stein_page_051.png",
    "newspaper_fe5ed29024932fad071afc53807b16ba_4.jpg",
    "page-2329f04a-41b3-435b-993a-a0652294b07d.png",
    "docstructbench_llm-raw-scihub-o.O-j.ergon.2004.09.009.pdf_13.jpg",
)
SOURCE_CANARY = {
    "repository": "cristh99/notebooks",
    "pr": 11,
    "run_id": 30833428126,
    "job_id": 91752687409,
    "artifact_id": 8864530547,
    "artifact_sha256": "6a5459ed4e004c4fe7f7a0692ad6d8b7dd67ef51bb0ca9a5afc4185fb10f47b7",
    "stable_payload_sha256": "850d97ca9183a0ea4a1dbd834cc1a1f824db2cbd0db717453285f5f48030cbd9",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_versions(names: Iterable[str]) -> dict[str, str]:
    result = {}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "not-installed"
    return result


def clamp_box(
    box: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    return (
        max(0, min(left, width - 1)),
        max(0, min(top, height - 1)),
        max(1, min(right, width)),
        max(1, min(bottom, height)),
    )


def extract_tesseract_numeric_candidates(
    image_path: Path,
    page_id: str,
    crops_dir: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    data = pytesseract.image_to_data(
        image,
        lang="eng",
        config="--oem 1 --psm 3",
        output_type=pytesseract.Output.DICT,
    )
    baseline_numbers: list[str] = []
    candidates: list[dict[str, Any]] = []
    line_words: dict[tuple[int, int, int], list[str]] = defaultdict(list)
    for word_index, raw_text in enumerate(data["text"]):
        text = core.normalize_text(str(raw_text))
        if not text:
            continue
        line_key = (
            int(data["block_num"][word_index]),
            int(data["par_num"][word_index]),
            int(data["line_num"][word_index]),
        )
        line_words[line_key].append(text)
        tokens = numeric_tokens(text)
        baseline_start = len(baseline_numbers)
        baseline_numbers.extend(tokens)
        if len(tokens) != 1:
            continue
        left = int(data["left"][word_index])
        top = int(data["top"][word_index])
        word_width = int(data["width"][word_index])
        word_height = int(data["height"][word_index])
        margin = max(3, round(word_height * 0.20))
        box = clamp_box(
            (
                left - margin,
                top - margin,
                left + word_width + margin,
                top + word_height + margin,
            ),
            image.width,
            image.height,
        )
        crop = image.crop(box)
        candidate_id = (
            hashlib.sha256(page_id.encode("utf-8")).hexdigest()[:12]
            + f"-{word_index:05d}"
        )
        crop_path = crops_dir / f"{candidate_id}.png"
        crop.save(crop_path, format="PNG", optimize=True)
        try:
            confidence = max(
                0.0,
                min(1.0, float(data["conf"][word_index]) / 100.0),
            )
        except (TypeError, ValueError):
            confidence = 0.0
        candidates.append(
            {
                "candidate_id": candidate_id,
                "page_id": page_id,
                "baseline_index": baseline_start,
                "baseline_token": tokens[0],
                "tesseract_text": text,
                "tesseract_confidence": confidence,
                "bbox": list(box),
                "crop_path": str(crop_path),
                "crop_sha256": sha256_file(crop_path),
            }
        )
    text = "\n".join(" ".join(words) for _, words in sorted(line_words.items()))
    return {
        "text": text,
        "baseline_numbers": baseline_numbers,
        "candidates": candidates,
        "latency_seconds": time.perf_counter() - started,
        "word_count": sum(len(words) for words in line_words.values()),
    }


def result_mapping(value: Any) -> Mapping[str, Any]:
    return core._mapping_from_result(value)


def parse_recognition_result(value: Any) -> tuple[str, float | None]:
    mapping = result_mapping(value)
    text = core._find_key(mapping, "rec_text")
    score = core._find_key(mapping, "rec_score")
    if text is None:
        texts = core._find_key(mapping, "rec_texts")
        if texts is not None:
            texts = list(texts)
            text = texts[0] if len(texts) == 1 else " ".join(map(str, texts))
    if score is None:
        scores = core._find_key(mapping, "rec_scores")
        if scores is not None:
            scores = list(scores)
            score = scores[0] if len(scores) == 1 else None
    return core.normalize_text(str(text or "")), None if score is None else float(score)


def run_small_recognition(
    crop_paths: list[Path],
) -> tuple[list[tuple[str, float | None]], dict[str, float]]:
    if not crop_paths:
        return [], {
            "model_initialization_seconds": 0.0,
            "batch_inference_seconds": 0.0,
        }
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "HUGGINGFACE")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import TextRecognition

    started = time.perf_counter()
    model = TextRecognition(
        model_name="PP-OCRv6_small_rec",
        device="cpu",
        enable_mkldnn=False,
    )
    initialized = time.perf_counter()
    outputs = list(
        model.predict(input=[str(path) for path in crop_paths], batch_size=32)
    )
    finished = time.perf_counter()
    if len(outputs) != len(crop_paths):
        raise RuntimeError(
            f"recognition denominator mismatch: {len(outputs)} outputs for "
            f"{len(crop_paths)} crops"
        )
    return [parse_recognition_result(item) for item in outputs], {
        "model_initialization_seconds": initialized - started,
        "batch_inference_seconds": finished - initialized,
    }


def model_cache_identity() -> dict[str, Any]:
    roots = [Path.home() / ".paddlex", Path.home() / ".cache" / "paddlex"]
    entries: list[tuple[str, int, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(
            item for item in root.rglob("*") if item.is_file() and not item.is_symlink()
        ):
            try:
                entries.append(
                    (
                        str(path.relative_to(Path.home())),
                        path.stat().st_size,
                        sha256_file(path),
                    )
                )
            except OSError:
                continue
    return {
        "file_count": len(entries),
        "bytes": sum(item[1] for item in entries),
        "aggregate_sha256": hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
    }


def build_report(output_dir: Path) -> dict[str, Any]:
    annotation_path = Path(
        hf_hub_download(
            DATASET_ID,
            ANNOTATION_FILE,
            repo_type="dataset",
            revision=DATASET_REVISION,
        )
    )
    if sha256_file(annotation_path) != ANNOTATION_SHA256:
        raise RuntimeError("annotation hash drift")
    raw_pages = json.loads(annotation_path.read_text(encoding="utf-8"))
    page_map = {}
    for raw in raw_pages:
        try:
            page = core.ground_truth_from_page(raw)
        except (TypeError, ValueError):
            continue
        page_map[page.page_id] = page
    if any(page_id not in page_map for page_id in SELECTED_PAGES):
        missing = [page_id for page_id in SELECTED_PAGES if page_id not in page_map]
        raise RuntimeError(f"frozen pages missing: {missing}")

    inputs_dir = output_dir / "inputs"
    crops_dir = output_dir / "crops"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)
    input_manifest = []
    local_images: dict[str, Path] = {}
    for index, page_id in enumerate(SELECTED_PAGES):
        dataset_path = page_id if page_id.startswith("images/") else f"images/{page_id}"
        source = Path(
            hf_hub_download(
                DATASET_ID,
                dataset_path,
                repo_type="dataset",
                revision=DATASET_REVISION,
            )
        )
        destination = inputs_dir / f"{index:02d}-{Path(page_id).name}"
        destination.write_bytes(source.read_bytes())
        local_images[page_id] = destination
        input_manifest.append(
            {
                "page_id": page_id,
                "dataset_path": dataset_path,
                "sha256": sha256_file(destination),
                "bytes": destination.stat().st_size,
            }
        )

    pages: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    tesseract_total = 0.0
    for page_id in SELECTED_PAGES:
        gt = page_map[page_id]
        extracted = extract_tesseract_numeric_candidates(
            local_images[page_id], page_id, crops_dir
        )
        tesseract_total += float(extracted["latency_seconds"])
        reference_numbers = list(numeric_tokens(gt.text))
        baseline_numbers = list(extracted["baseline_numbers"])
        alignment = align_prediction_to_reference(reference_numbers, baseline_numbers)
        for candidate in extracted["candidates"]:
            assignment = alignment["assignments"][candidate["baseline_index"]]
            candidate["alignment_state"] = assignment["state"]
            candidate["target_token"] = assignment["target"]
            candidates.append(candidate)
        pages.append(
            {
                "page_id": page_id,
                "attributes": {
                    "domain": gt.domain,
                    "layout": gt.layout,
                    "has_table": gt.has_table,
                    "has_formula": gt.has_formula,
                    "fuzzy_scan": gt.fuzzy_scan,
                },
                "reference_numbers": reference_numbers,
                "baseline_numbers": baseline_numbers,
                "baseline_numeric_accuracy": sequence_accuracy(
                    reference_numbers, baseline_numbers
                ),
                "alignment_distance": alignment["distance"],
                "deletions": alignment["deletions"],
                "candidate_ids": [
                    item["candidate_id"] for item in extracted["candidates"]
                ],
                "tesseract_latency_seconds": extracted["latency_seconds"],
                "tesseract_word_count": extracted["word_count"],
            }
        )

    crop_paths = [Path(item["crop_path"]) for item in candidates]
    recognition, timing = run_small_recognition(crop_paths)
    for candidate, (text, score) in zip(candidates, recognition, strict=True):
        tokens = numeric_tokens(text)
        candidate["paddle_text"] = text
        candidate["paddle_token"] = tokens[0] if len(tokens) == 1 else None
        candidate["paddle_confidence"] = score
        candidate.pop("crop_path", None)

    policy = RescuePolicy()
    candidates = apply_policy(candidates, policy)
    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_page[candidate["page_id"]].append(candidate)
    for page in pages:
        rescued = list(page["baseline_numbers"])
        for candidate in by_page[page["page_id"]]:
            if candidate["decision"]["propose_change"]:
                rescued[candidate["baseline_index"]] = candidate["paddle_token"]
        page["strict_rescued_numbers"] = rescued
        page["strict_numeric_accuracy"] = sequence_accuracy(
            page["reference_numbers"], rescued
        )

    summary = summarize_candidates(candidates)
    baseline_accuracy = sum(
        page["baseline_numeric_accuracy"] for page in pages
    ) / len(pages)
    strict_accuracy = sum(
        page["strict_numeric_accuracy"] for page in pages
    ) / len(pages)
    stable = {
        "schema": SCHEMA,
        "source_canary": SOURCE_CANARY,
        "dataset": {
            "id": DATASET_ID,
            "revision": DATASET_REVISION,
            "annotation_file": ANNOTATION_FILE,
            "annotation_sha256": ANNOTATION_SHA256,
            "selected_pages": list(SELECTED_PAGES),
            "input_manifest": input_manifest,
        },
        "policy": policy.to_data(),
        "pages": pages,
        "candidates": candidates,
        "metrics": {
            "candidate_summary": summary,
            "baseline_numeric_accuracy": baseline_accuracy,
            "strict_numeric_accuracy": strict_accuracy,
            "strict_delta_pp": 100 * (strict_accuracy - baseline_accuracy),
        },
        "denominators": {
            "pages": len(pages),
            "candidates": len(candidates),
            "page_engine_pairs_in_source_canary": 16,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "paid_api_used": False,
            "gpu_used": False,
            "logic_power_in_inference": False,
            "full_page_secondary_ocr": False,
        },
    }
    stable_hash = digest_payload(stable)
    process = psutil.Process()
    runtime = {
        **timing,
        "tesseract_total_seconds": tesseract_total,
        "tesseract_seconds_per_page": tesseract_total / len(pages),
        "incremental_recognition_seconds_per_page": timing[
            "batch_inference_seconds"
        ]
        / len(pages),
        "incremental_recognition_seconds_per_candidate": timing[
            "batch_inference_seconds"
        ]
        / max(len(candidates), 1),
        "cold_pipeline_seconds_per_page": (
            tesseract_total
            + timing["model_initialization_seconds"]
            + timing["batch_inference_seconds"]
        )
        / len(pages),
        "peak_rss_mb": process.memory_info().rss / 1024 / 1024,
    }
    report = {
        **stable,
        "stable_payload_sha256": stable_hash,
        "runtime": runtime,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "packages": package_versions(
                [
                    "paddleocr",
                    "paddlepaddle",
                    "pytesseract",
                    "Pillow",
                    "huggingface-hub",
                    "psutil",
                ]
            ),
            "tesseract_version": subprocess.check_output(
                ["tesseract", "--version"],
                text=True,
                stderr=subprocess.STDOUT,
            ).splitlines()[0],
            "small_recognition_model_cache": model_cache_identity(),
        },
    }
    return report


def write_report(report: Mapping[str, Any], output_dir: Path) -> Path:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "numeric_rescue.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (reports_dir / "numeric_rescue.sha256").write_text(
        f"{sha256_file(path)}  numeric_rescue.json\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_numeric_rescue_v1/run"),
    )
    args = parser.parse_args()
    report = build_report(args.output_dir)
    path = write_report(report, args.output_dir)
    print(
        json.dumps(
            {
                "report": str(path),
                "stable_payload_sha256": report["stable_payload_sha256"],
                "metrics": report["metrics"],
                "runtime": report["runtime"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
