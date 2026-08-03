"""Apply the frozen geometry winner to Tesseract lines on sealed real pages."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image
import pytesseract

from ocr_reading_order_real_v1.core import (
    ANNOTATION_FILE,
    DATASET_ID,
    EXPECTED_ANNOTATION_SHA256,
    PINNED_REVISION,
    Block,
    CANDIDATES,
    bbox_from_poly,
    canonical_json,
    levenshtein,
    sha256_bytes,
    split_name,
)

SCHEMA = "ocr-reading-order-tesseract-v1/report/1"
TARGET_PAGES = 50
BASE_QUOTA_PER_LAYOUT = 8
TEXT_CATEGORIES = frozenset({
    "title", "text_block", "list_group", "reference",
    "figure_caption", "figure_footnote", "table_caption", "table_footnote",
    "equation_caption", "equation_explanation", "header", "footer",
    "page_number", "page_footnote", "code_txt", "code_txt_caption",
})


@dataclass(frozen=True)
class GTBlock:
    block_id: str
    order: int
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class GTPage:
    page_id: str
    width: float
    height: float
    layout: str
    domain: str
    language: str
    blocks: tuple[GTBlock, ...]


@dataclass(frozen=True)
class OCRLine:
    line_id: str
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").replace("\u00ad", "")
    value = re.sub(r"[\t\r\f\v]+", " ", value)
    value = re.sub(r" +", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def page_from_raw(raw: Mapping[str, Any]) -> GTPage | None:
    info = raw.get("page_info") or {}
    page_id = str(info.get("image_path") or "").strip()
    attrs = info.get("page_attribute") or {}
    language = str(attrs.get("language") or "unknown")
    if not page_id or language.casefold() not in {"english", "en"}:
        return None
    if split_name(page_id) != "holdout":
        return None
    width = float(info.get("width") or 0)
    height = float(info.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    blocks: list[GTBlock] = []
    for index, item in enumerate(raw.get("layout_dets") or []):
        if item.get("ignore", False):
            continue
        category = str(item.get("category_type") or "")
        if category not in TEXT_CATEGORIES:
            continue
        order = item.get("order")
        text = normalize_text(str(item.get("text") or ""))
        if isinstance(order, bool) or not isinstance(order, int) or not text:
            continue
        try:
            bbox = bbox_from_poly(item.get("poly") or item.get("bbox"))
        except (TypeError, ValueError):
            continue
        blocks.append(GTBlock(f"{page_id}::{item.get('anno_id', index)}::{index}", order, text, bbox))
    if len(blocks) < 2:
        return None
    return GTPage(
        page_id,
        width,
        height,
        str(attrs.get("layout") or "unknown"),
        str(attrs.get("data_source") or "unknown"),
        language,
        tuple(blocks),
    )


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _round_robin_domain(pages: Sequence[GTPage], limit: int) -> list[GTPage]:
    groups: dict[str, list[GTPage]] = defaultdict(list)
    for page in pages:
        groups[page.domain].append(page)
    for group in groups.values():
        group.sort(key=lambda page: _hash_key(page.page_id))
    selected: list[GTPage] = []
    domains = sorted(groups)
    cursor = 0
    while len(selected) < limit and any(groups.values()):
        domain = domains[cursor % len(domains)]
        cursor += 1
        if groups[domain]:
            selected.append(groups[domain].pop(0))
    return selected


def select_pages(pages: Sequence[GTPage], target: int = TARGET_PAGES) -> list[GTPage]:
    by_layout: dict[str, list[GTPage]] = defaultdict(list)
    for page in pages:
        by_layout[page.layout].append(page)
    selected: list[GTPage] = []
    selected_ids: set[str] = set()
    for layout in sorted(by_layout):
        chosen = _round_robin_domain(by_layout[layout], BASE_QUOTA_PER_LAYOUT)
        selected.extend(chosen)
        selected_ids.update(page.page_id for page in chosen)
    remainder = sorted(
        (page for page in pages if page.page_id not in selected_ids),
        key=lambda page: (_hash_key(page.page_id), page.layout, page.domain),
    )
    selected.extend(remainder[: max(0, target - len(selected))])
    selected = selected[:target]
    if len(selected) != target:
        raise RuntimeError(f"only {len(selected)} eligible pages; need {target}")
    return selected


def resolve_annotation(annotation: Path | None) -> Path:
    if annotation is not None:
        path = annotation
    else:
        from huggingface_hub import hf_hub_download

        path = Path(hf_hub_download(DATASET_ID, ANNOTATION_FILE, repo_type="dataset", revision=PINNED_REVISION))
    digest = sha256_file(path)
    if digest != EXPECTED_ANNOTATION_SHA256:
        raise RuntimeError(f"annotation hash mismatch: {digest}")
    return path


def _union(boxes: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    values = list(boxes)
    return (
        min(box[0] for box in values),
        min(box[1] for box in values),
        max(box[2] for box in values),
        max(box[3] for box in values),
    )


def run_tesseract(image_path: Path) -> tuple[list[OCRLine], float]:
    started = time.perf_counter()
    data = pytesseract.image_to_data(
        Image.open(image_path).convert("RGB"),
        lang="eng",
        config="--oem 1 --psm 3",
        output_type=pytesseract.Output.DICT,
    )
    groups: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, text in enumerate(data["text"]):
        if normalize_text(str(text)):
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            groups[key].append(index)
    lines: list[OCRLine] = []
    for line_index, indices in enumerate(groups.values()):
        text = " ".join(normalize_text(str(data["text"][index])) for index in indices)
        boxes = [
            (
                float(data["left"][index]),
                float(data["top"][index]),
                float(data["left"][index] + data["width"][index]),
                float(data["top"][index] + data["height"][index]),
            )
            for index in indices
        ]
        confidences = [float(data["conf"][index]) for index in indices if float(data["conf"][index]) >= 0]
        lines.append(
            OCRLine(
                f"line-{line_index}",
                text,
                _union(boxes),
                sum(confidences) / max(len(confidences), 1) / 100.0,
            )
        )
    return lines, time.perf_counter() - started


def _as_geometry(lines: Sequence[OCRLine]) -> list[Block]:
    return [Block(line.line_id, 0, "tesseract_line", line.bbox) for line in lines]


def reorder(lines: Sequence[OCRLine], algorithm: str) -> tuple[list[OCRLine], float]:
    candidate = next(candidate for candidate in CANDIDATES if candidate.name == algorithm)
    by_id = {line.line_id: line for line in lines}
    started = time.perf_counter()
    ordered_blocks = candidate.orderer(_as_geometry(lines), 1.0, 1.0)
    elapsed = time.perf_counter() - started
    return [by_id[block.block_id] for block in ordered_blocks], elapsed


def _area(box: Sequence[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(left: Sequence[float], right: Sequence[float]) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0, min(left[3], right[3]) - max(left[1], right[1])
    )


def match_lines(lines: Sequence[OCRLine], gt_blocks: Sequence[GTBlock]) -> dict[str, str]:
    matches: dict[str, str] = {}
    for line in lines:
        best: tuple[float, float, str] | None = None
        for gt in gt_blocks:
            intersection = _intersection(line.bbox, gt.bbox)
            line_coverage = intersection / max(_area(line.bbox), 1e-9)
            union = _area(line.bbox) + _area(gt.bbox) - intersection
            iou = intersection / max(union, 1e-9)
            score = (line_coverage, iou, gt.block_id)
            if best is None or score > best:
                best = score
        if best is not None and (best[0] >= 0.50 or best[1] >= 0.10):
            matches[line.line_id] = best[2]
    return matches


def _unique_matched_sequence(lines: Sequence[OCRLine], matches: Mapping[str, str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        gt_id = matches.get(line.line_id)
        if gt_id is not None and gt_id not in seen:
            result.append(gt_id)
            seen.add(gt_id)
    return result


def sequence_metrics(page: GTPage, lines: Sequence[OCRLine], matches: Mapping[str, str]) -> dict[str, Any]:
    gt_by_id = {block.block_id: block for block in page.blocks}
    predicted = _unique_matched_sequence(lines, matches)
    matched_ids = set(predicted)
    conditional_gt = [
        block.block_id
        for block in sorted((block for block in page.blocks if block.block_id in matched_ids), key=lambda block: (block.order, block.block_id))
    ]
    full_gt = [block.block_id for block in sorted(page.blocks, key=lambda block: (block.order, block.block_id))]
    conditional_edit = levenshtein(conditional_gt, predicted) / max(len(conditional_gt), len(predicted), 1)
    coverage_edit = levenshtein(full_gt, predicted) / max(len(full_gt), len(predicted), 1)
    correct = 0
    comparable = 0
    for index, left_id in enumerate(predicted):
        for right_id in predicted[index + 1 :]:
            left_order = gt_by_id[left_id].order
            right_order = gt_by_id[right_id].order
            if left_order == right_order:
                continue
            comparable += 1
            if left_order < right_order:
                correct += 1
    return {
        "matched_gt_blocks": len(matched_ids),
        "gt_blocks": len(page.blocks),
        "match_coverage": len(matched_ids) / max(len(page.blocks), 1),
        "conditional_read_order_edit": conditional_edit,
        "coverage_aware_read_order_edit": coverage_edit,
        "pairwise_accuracy": correct / comparable if comparable else 1.0,
        "exact_on_matched": predicted == conditional_gt,
    }


def text_metrics(reference: str, prediction: str) -> dict[str, float | int]:
    ref = normalize_text(reference)
    pred = normalize_text(prediction)
    ref_words = ref.split()
    pred_words = pred.split()
    return {
        "reference_characters": len(ref),
        "prediction_characters": len(pred),
        "character_accuracy": max(0.0, 1.0 - levenshtein(ref, pred) / max(len(ref), 1)),
        "word_accuracy": max(0.0, 1.0 - levenshtein(ref_words, pred_words) / max(len(ref_words), 1)),
    }


def evaluate_page(page: GTPage, lines: Sequence[OCRLine], algorithm: str, matches: Mapping[str, str]) -> tuple[dict[str, Any], float]:
    ordered, overhead = reorder(lines, algorithm)
    prediction = "\n".join(line.text for line in ordered)
    reference = "\n".join(block.text for block in sorted(page.blocks, key=lambda block: (block.order, block.block_id)))
    return {
        "text": text_metrics(reference, prediction),
        "order": sequence_metrics(page, ordered, matches),
    }, overhead


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / max(len(items), 1)


def aggregate(rows: Sequence[Mapping[str, Any]], algorithm: str) -> dict[str, Any]:
    return {
        "pages": len(rows),
        "mean_character_accuracy": mean(float(row[algorithm]["text"]["character_accuracy"]) for row in rows),
        "mean_word_accuracy": mean(float(row[algorithm]["text"]["word_accuracy"]) for row in rows),
        "mean_conditional_read_order_edit": mean(float(row[algorithm]["order"]["conditional_read_order_edit"]) for row in rows),
        "mean_coverage_aware_read_order_edit": mean(float(row[algorithm]["order"]["coverage_aware_read_order_edit"]) for row in rows),
        "mean_pairwise_accuracy": mean(float(row[algorithm]["order"]["pairwise_accuracy"]) for row in rows),
        "exact_on_matched_rate": mean(float(bool(row[algorithm]["order"]["exact_on_matched"])) for row in rows),
        "mean_match_coverage": mean(float(row[algorithm]["order"]["match_coverage"]) for row in rows),
    }


def build_report(annotation_path: Path, output_dir: Path) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download

    raw = json.loads(annotation_path.read_text(encoding="utf-8"))
    pages = [page for item in raw if (page := page_from_raw(item)) is not None]
    selected = select_pages(pages)
    rows: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    runtime_rows: list[dict[str, float]] = []
    for page in selected:
        dataset_path = page.page_id if page.page_id.startswith("images/") else f"images/{page.page_id}"
        image_path = Path(hf_hub_download(DATASET_ID, dataset_path, repo_type="dataset", revision=PINNED_REVISION))
        lines, tesseract_seconds = run_tesseract(image_path)
        matches = match_lines(lines, page.blocks)
        baseline, baseline_overhead = evaluate_page(page, lines, "yx_baseline", matches)
        geometry, geometry_overhead = evaluate_page(page, lines, "xycut_loose", matches)
        rows.append(
            {
                "page_id": page.page_id,
                "layout": page.layout,
                "domain": page.domain,
                "baseline": baseline,
                "geometry": geometry,
            }
        )
        observations.append(
            {
                "page_id": page.page_id,
                "image_sha256": sha256_file(image_path),
                "image_bytes": image_path.stat().st_size,
                "lines": [
                    {
                        "line_id": line.line_id,
                        "text": line.text,
                        "bbox": list(line.bbox),
                        "confidence": line.confidence,
                    }
                    for line in lines
                ],
                "matches": dict(sorted(matches.items())),
            }
        )
        runtime_rows.append(
            {
                "tesseract_seconds": tesseract_seconds,
                "baseline_overhead_seconds": baseline_overhead,
                "geometry_overhead_seconds": geometry_overhead,
            }
        )

    baseline_aggregate = aggregate(rows, "baseline")
    geometry_aggregate = aggregate(rows, "geometry")
    baseline_edit = float(baseline_aggregate["mean_conditional_read_order_edit"])
    geometry_edit = float(geometry_aggregate["mean_conditional_read_order_edit"])
    relative_improvement = (baseline_edit - geometry_edit) / baseline_edit if baseline_edit > 0 else 0.0
    harmful_pages = sum(
        float(row["geometry"]["order"]["conditional_read_order_edit"])
        > float(row["baseline"]["order"]["conditional_read_order_edit"]) + 1e-12
        for row in rows
    )
    mean_tesseract = mean(row["tesseract_seconds"] for row in runtime_rows)
    mean_geometry_overhead = mean(row["geometry_overhead_seconds"] for row in runtime_rows)
    overhead_ratio = mean_geometry_overhead / mean_tesseract if mean_tesseract > 0 else 1.0
    pass_gate = (
        relative_improvement >= 0.20
        and geometry_aggregate["mean_character_accuracy"] >= baseline_aggregate["mean_character_accuracy"] - 1e-12
        and geometry_aggregate["mean_word_accuracy"] >= baseline_aggregate["mean_word_accuracy"] - 1e-12
        and harmful_pages / len(rows) <= 0.10
        and geometry_aggregate["mean_match_coverage"] >= 0.70
    )
    decision = {
        "verdict": "PROMOTE_TO_HONDURAN_HOLDOUT" if pass_gate else "DO_NOT_PROMOTE",
        "relative_conditional_edit_improvement": relative_improvement,
        "harmful_pages": harmful_pages,
        "harmful_page_rate": harmful_pages / len(rows),
        "next_experiment": (
            "sealed Honduran public-document holdout with frozen Tesseract plus XY-cut"
            if pass_gate
            else "geometry plus block semantics on the same frozen pages"
        ),
        "quality_gate_pass": pass_gate,
        "automatic_production_change": False,
    }
    stable_payload = {
        "schema": SCHEMA,
        "dataset": {
            "id": DATASET_ID,
            "revision": PINNED_REVISION,
            "annotation_sha256": EXPECTED_ANNOTATION_SHA256,
            "selection": "English OmniDocBench geometry holdout; 8 per layout then deterministic fill to 50",
            "selected_page_ids": [page.page_id for page in selected],
            "selected_page_ids_sha256": sha256_bytes(canonical_json([page.page_id for page in selected]).encode("utf-8")),
        },
        "frozen_algorithm": {
            "name": "xycut_loose",
            "source_pr": 30,
            "source_stable_payload_sha256": "7a60f4866be4d4a37f74a82acf40057277983b7523c2d61dd9de4c473d1cd8fa",
            "retuned_after_holdout": False,
        },
        "observations": observations,
        "rows": rows,
        "aggregate": {"baseline": baseline_aggregate, "geometry": geometry_aggregate},
        "decision": decision,
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "paid_api_used": False,
            "gpu_used": False,
            "second_ocr_pass_used": False,
            "logic_power_in_runtime": False,
        },
    }
    stable_sha = sha256_bytes(canonical_json(stable_payload).encode("utf-8"))
    return {
        **stable_payload,
        "stable_payload_sha256": stable_sha,
        "runtime": {
            "mean_tesseract_seconds_per_page": mean_tesseract,
            "mean_geometry_overhead_seconds_per_page": mean_geometry_overhead,
            "mean_geometry_overhead_microseconds_per_page": mean_geometry_overhead * 1_000_000,
            "geometry_overhead_ratio": overhead_ratio,
            "total_tesseract_seconds": sum(row["tesseract_seconds"] for row in runtime_rows),
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "tesseract": subprocess.check_output(["tesseract", "--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0],
        },
    }


def write_report(report: Mapping[str, Any], output_dir: Path) -> Path:
    reports = output_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "tesseract_order.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (reports / "tesseract_order.sha256").write_text(f"{sha256_file(path)}  tesseract_order.json\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotation", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_reading_order_tesseract_v1/run"))
    args = parser.parse_args()
    annotation = resolve_annotation(args.annotation)
    report = build_report(annotation, args.output_dir)
    path = write_report(report, args.output_dir)
    print(json.dumps({
        "report": str(path),
        "aggregate": report["aggregate"],
        "decision": report["decision"],
        "runtime": report["runtime"],
        "stable_payload_sha256": report["stable_payload_sha256"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
