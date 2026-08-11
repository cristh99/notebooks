from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
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

from huggingface_hub import HfApi, hf_hub_download
from PIL import Image
import psutil
import pytesseract

DATASET_ID = "opendatalab/OmniDocBench"
ANNOTATION_FILE = "OmniDocBench.json"
SCHEMA = "ocr-sota-real-canary-v2/report/1"
TEXT_CATEGORIES = {
    "title", "text_block", "figure_caption", "figure_footnote",
    "table_caption", "table_footnote", "equation_caption", "header",
    "footer", "page_number", "page_footnote", "code_txt",
    "code_txt_caption", "reference", "text_span",
}
NUMERIC_RE = re.compile(r"(?<!\w)[+-]?(?:\d{1,3}(?:[.,\s]\d{3})+|\d+)(?:[.,]\d+)?%?(?!\w)")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = value.replace("\u00ad", "")
    value = re.sub(r"[\t\r\f\v]+", " ", value)
    value = re.sub(r"[ ]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def levenshtein(left: Sequence[Any], right: Sequence[Any]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, start=1):
        current = [i]
        for j, b in enumerate(right, start=1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def text_metrics(reference: str, prediction: str) -> dict[str, Any]:
    ref = normalize_text(reference)
    pred = normalize_text(prediction)
    ref_words, pred_words = ref.split(), pred.split()
    ref_numbers = tuple(match.group(0).replace(" ", "") for match in NUMERIC_RE.finditer(ref))
    pred_numbers = tuple(match.group(0).replace(" ", "") for match in NUMERIC_RE.finditer(pred))
    number_distance = levenshtein(ref_numbers, pred_numbers)
    return {
        "reference_characters": len(ref),
        "prediction_characters": len(pred),
        "cer": levenshtein(ref, pred) / max(len(ref), 1),
        "wer": levenshtein(ref_words, pred_words) / max(len(ref_words), 1),
        "numeric_reference_count": len(ref_numbers),
        "numeric_prediction_count": len(pred_numbers),
        "numeric_sequence_accuracy": 1.0 - number_distance / max(len(ref_numbers), len(pred_numbers), 1),
        "numeric_exact": ref_numbers == pred_numbers,
    }


def bbox_from_poly(poly: Sequence[float] | Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    if not poly:
        return (0.0, 0.0, 0.0, 0.0)
    if isinstance(poly[0], (list, tuple)):
        points = [(float(point[0]), float(point[1])) for point in poly]
    else:
        flat = [float(value) for value in poly]
        points = list(zip(flat[0::2], flat[1::2], strict=True))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def box_area(box: Sequence[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersection_area(a: Sequence[float], b: Sequence[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def region_score(gt_boxes: Sequence[Sequence[float]], pred_boxes: Sequence[Sequence[float]], threshold: float = 0.5) -> dict[str, Any]:
    gt_covered = []
    for gt in gt_boxes:
        area = box_area(gt)
        coverage = min(1.0, sum(intersection_area(gt, pred) for pred in pred_boxes) / area) if area else 0.0
        gt_covered.append(coverage)
    pred_supported = []
    for pred in pred_boxes:
        area = box_area(pred)
        support = min(1.0, sum(intersection_area(pred, gt) for gt in gt_boxes) / area) if area else 0.0
        pred_supported.append(support)
    tp_recall = sum(value >= threshold for value in gt_covered)
    tp_precision = sum(value >= threshold for value in pred_supported)
    recall = tp_recall / max(len(gt_boxes), 1)
    precision = tp_precision / max(len(pred_boxes), 1)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "ground_truth_regions": len(gt_boxes),
        "prediction_regions": len(pred_boxes),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "mean_ground_truth_coverage": sum(gt_covered) / max(len(gt_covered), 1),
        "mean_prediction_support": sum(pred_supported) / max(len(pred_supported), 1),
    }


@dataclass(frozen=True)
class GroundTruthPage:
    page_id: str
    image_path: str
    width: int
    height: int
    domain: str
    language: str
    layout: str
    fuzzy_scan: bool
    has_table: bool
    has_formula: bool
    text: str
    boxes: tuple[tuple[float, float, float, float], ...]


def page_attributes(page: Mapping[str, Any]) -> Mapping[str, Any]:
    info = page.get("page_info") or {}
    return info.get("page_attribute") or info.get("attribute") or {}


def ground_truth_from_page(page: Mapping[str, Any]) -> GroundTruthPage:
    info = page.get("page_info") or {}
    image_path = str(info.get("image_path") or info.get("image") or "")
    if not image_path:
        raise ValueError("annotation page has no image_path")
    attrs = page_attributes(page)
    detections = [item for item in (page.get("layout_dets") or []) if not item.get("ignore", False)]
    ordered = sorted(
        detections,
        key=lambda item: (
            item.get("order") is None,
            item.get("order") if isinstance(item.get("order"), int) else 10**9,
            bbox_from_poly(item.get("poly") or item.get("bbox") or [0, 0, 0, 0])[1],
            bbox_from_poly(item.get("poly") or item.get("bbox") or [0, 0, 0, 0])[0],
        ),
    )
    texts: list[str] = []
    boxes: list[tuple[float, float, float, float]] = []
    for item in ordered:
        category = str(item.get("category_type") or item.get("category") or "")
        text = normalize_text(str(item.get("text") or ""))
        if category in TEXT_CATEGORIES and text:
            texts.append(text)
            boxes.append(bbox_from_poly(item.get("poly") or item.get("bbox") or [0, 0, 0, 0]))
    categories = {str(item.get("category_type") or "") for item in detections}
    return GroundTruthPage(
        page_id=image_path,
        image_path=image_path,
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        domain=str(attrs.get("data_source") or "unknown"),
        language=str(attrs.get("language") or "unknown"),
        layout=str(attrs.get("layout") or "unknown"),
        fuzzy_scan=bool(attrs.get("fuzzy_scan", False)),
        has_table="table" in categories,
        has_formula=bool({"equation_isolated", "equation_inline"} & categories),
        text="\n".join(texts),
        boxes=tuple(boxes),
    )


def select_pages(raw_pages: Sequence[Mapping[str, Any]], count: int) -> list[GroundTruthPage]:
    pages: list[GroundTruthPage] = []
    for raw in raw_pages:
        try:
            page = ground_truth_from_page(raw)
        except (TypeError, ValueError):
            continue
        if page.language != "en" or len(page.text) < 120 or not page.boxes:
            continue
        pages.append(page)
    if len(pages) < count:
        raise RuntimeError(f"only {len(pages)} eligible English pages; need {count}")
    pages.sort(key=lambda item: sha256_bytes(item.image_path.encode("utf-8")))
    selectors = [
        ("table", lambda page: page.has_table),
        ("formula", lambda page: page.has_formula),
        ("fuzzy", lambda page: page.fuzzy_scan),
        ("multi_column", lambda page: page.layout in {"double_column", "three_column", "1andmore_column"}),
        ("note", lambda page: page.domain == "note"),
        ("plain", lambda page: not page.has_table and not page.has_formula and not page.fuzzy_scan),
    ]
    selected: list[GroundTruthPage] = []
    used: set[str] = set()
    for _, predicate in selectors:
        match = next((page for page in pages if page.page_id not in used and predicate(page)), None)
        if match is not None:
            selected.append(match)
            used.add(match.page_id)
        if len(selected) == count:
            return selected
    for page in pages:
        if page.page_id not in used:
            selected.append(page)
            used.add(page.page_id)
        if len(selected) == count:
            break
    if len(selected) != count:
        raise AssertionError("selection denominator drift")
    return selected


def _union(boxes: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    values = list(boxes)
    return (
        min(box[0] for box in values), min(box[1] for box in values),
        max(box[2] for box in values), max(box[3] for box in values),
    )


def run_tesseract(image_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    data = pytesseract.image_to_data(
        Image.open(image_path).convert("RGB"),
        lang="eng",
        config="--oem 1 --psm 3",
        output_type=pytesseract.Output.DICT,
    )
    groups: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, text in enumerate(data["text"]):
        if normalize_text(text):
            key = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
            groups[key].append(index)
    lines: list[dict[str, Any]] = []
    for indices in groups.values():
        text = " ".join(normalize_text(data["text"][index]) for index in indices)
        boxes = [
            (
                float(data["left"][index]), float(data["top"][index]),
                float(data["left"][index] + data["width"][index]),
                float(data["top"][index] + data["height"][index]),
            )
            for index in indices
        ]
        confidences = [float(data["conf"][index]) for index in indices if float(data["conf"][index]) >= 0]
        lines.append({"text": text, "bbox": list(_union(boxes)), "confidence": sum(confidences) / max(len(confidences), 1) / 100.0})
    lines.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return {"text": "\n".join(item["text"] for item in lines), "lines": lines, "latency_seconds": time.perf_counter() - started}


def _mapping_from_result(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        result: Any = value
    else:
        result = None
        for name in ("json", "to_dict", "to_json"):
            if not hasattr(value, name):
                continue
            candidate = getattr(value, name)
            candidate = candidate() if callable(candidate) else candidate
            if isinstance(candidate, str):
                candidate = json.loads(candidate)
            if isinstance(candidate, Mapping):
                result = candidate
                break
        if result is None and hasattr(value, "__dict__"):
            result = vars(value)
    if not isinstance(result, Mapping):
        raise TypeError(f"unsupported PaddleOCR result type: {type(value)!r}")
    while len(result) == 1 and next(iter(result)) in {"res", "result", "data"} and isinstance(next(iter(result.values())), Mapping):
        result = next(iter(result.values()))
    return result


def _find_key(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_key(child, key)
            if found is not None:
                return found
    return None


def parse_paddle_result(result_items: Iterable[Any]) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    raw_shapes: list[str] = []
    for item in result_items:
        mapping = _mapping_from_result(item)
        raw_shapes.append(",".join(sorted(str(key) for key in mapping.keys())))
        texts = _find_key(mapping, "rec_texts") or _find_key(mapping, "texts")
        polygons = _find_key(mapping, "rec_polys") or _find_key(mapping, "dt_polys") or _find_key(mapping, "polys")
        scores = _find_key(mapping, "rec_scores") or _find_key(mapping, "scores")
        if texts is None or polygons is None:
            continue
        texts = list(texts)
        polygons = list(polygons)
        scores = list(scores) if scores is not None else [None] * len(texts)
        if len(texts) != len(polygons):
            raise ValueError("PaddleOCR text/polygon denominator mismatch")
        for index, (text, polygon) in enumerate(zip(texts, polygons, strict=True)):
            clean = normalize_text(str(text))
            if clean:
                score = scores[index] if index < len(scores) else None
                lines.append({"text": clean, "bbox": list(bbox_from_poly(polygon)), "confidence": None if score is None else float(score)})
    if not lines:
        raise RuntimeError(f"PaddleOCR produced no parseable lines; result keys={raw_shapes}")
    lines.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return {"text": "\n".join(item["text"] for item in lines), "lines": lines, "result_keys": raw_shapes}


def make_paddle_engine() -> Any:
    from paddleocr import PaddleOCR
    return PaddleOCR(
        lang="en",
        ocr_version="PP-OCRv6",
        device="cpu",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def run_paddle(engine: Any, image_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    result = parse_paddle_result(engine.predict(input=str(image_path)))
    result["latency_seconds"] = time.perf_counter() - started
    return result


def package_versions(names: Iterable[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def tesseract_identity() -> dict[str, Any]:
    version = subprocess.check_output(["tesseract", "--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0]
    candidates = list(Path("/usr/share").glob("tesseract-ocr/*/tessdata/eng.traineddata"))
    model = candidates[0] if candidates else None
    return {"version": version, "eng_traineddata": None if model is None else {"path": str(model), "sha256": sha256_file(model), "bytes": model.stat().st_size}}


def model_cache_identity() -> dict[str, Any]:
    roots = [Path.home() / ".paddlex", Path.home() / ".paddleocr", Path.home() / ".cache" / "paddlex"]
    entries: list[tuple[str, int, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
            try:
                entries.append((str(path.relative_to(Path.home())), path.stat().st_size, sha256_file(path)))
            except OSError:
                continue
    aggregate = sha256_bytes(canonical_json(entries).encode("utf-8"))
    return {"file_count": len(entries), "bytes": sum(item[1] for item in entries), "aggregate_sha256": aggregate}


def evaluate(gt: GroundTruthPage, engine: str, prediction: Mapping[str, Any]) -> dict[str, Any]:
    boxes = [line["bbox"] for line in prediction["lines"]]
    return {
        "page_id": gt.page_id,
        "engine": engine,
        "attributes": {"domain": gt.domain, "language": gt.language, "layout": gt.layout, "fuzzy_scan": gt.fuzzy_scan, "has_table": gt.has_table, "has_formula": gt.has_formula},
        "text": text_metrics(gt.text, str(prediction["text"])),
        "text_region": region_score(gt.boxes, boxes),
        "latency_seconds": float(prediction["latency_seconds"]),
        "ground_truth_sha256": sha256_bytes(gt.text.encode("utf-8")),
        "prediction_sha256": sha256_bytes(str(prediction["text"]).encode("utf-8")),
        "prediction": {"text": prediction["text"], "lines": prediction["lines"]},
    }


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / max(len(items), 1)


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_engine: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_engine[str(row["engine"])].append(row)
    result: dict[str, Any] = {}
    for engine, engine_rows in sorted(by_engine.items()):
        result[engine] = {
            "pages": len(engine_rows),
            "character_accuracy": mean(max(0.0, 1.0 - float(row["text"]["cer"])) for row in engine_rows),
            "word_accuracy": mean(max(0.0, 1.0 - float(row["text"]["wer"])) for row in engine_rows),
            "numeric_sequence_accuracy": mean(float(row["text"]["numeric_sequence_accuracy"]) for row in engine_rows),
            "numeric_exact_rate": mean(float(bool(row["text"]["numeric_exact"])) for row in engine_rows),
            "text_region_f1": mean(float(row["text_region"]["f1"]) for row in engine_rows),
            "text_region_recall": mean(float(row["text_region"]["recall"]) for row in engine_rows),
            "latency_seconds_per_page": mean(float(row["latency_seconds"]) for row in engine_rows),
        }
    return result


def build_report(page_count: int, output_dir: Path, revision: str | None = None) -> dict[str, Any]:
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "HUGGINGFACE")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    api = HfApi()
    info = api.dataset_info(DATASET_ID, revision=revision or "main")
    pinned_revision = str(info.sha)
    annotation_path = Path(hf_hub_download(DATASET_ID, ANNOTATION_FILE, repo_type="dataset", revision=pinned_revision))
    raw_pages = json.loads(annotation_path.read_text(encoding="utf-8"))
    if not isinstance(raw_pages, list):
        raise TypeError("OmniDocBench annotation root must be a list")
    selected = select_pages(raw_pages, page_count)
    images_dir = output_dir / "inputs"
    images_dir.mkdir(parents=True, exist_ok=True)
    downloaded: dict[str, Path] = {}
    input_manifest = []
    for page in selected:
        dataset_path = page.image_path if page.image_path.startswith("images/") else f"images/{page.image_path}"
        source = Path(hf_hub_download(DATASET_ID, dataset_path, repo_type="dataset", revision=pinned_revision))
        destination = images_dir / Path(page.image_path).name
        destination.write_bytes(source.read_bytes())
        downloaded[page.page_id] = destination
        input_manifest.append({"page_id": page.page_id, "dataset_path": dataset_path, "sha256": sha256_file(destination), "bytes": destination.stat().st_size})

    paddle = make_paddle_engine()
    rows: list[dict[str, Any]] = []
    process = psutil.Process()
    for page in selected:
        path = downloaded[page.page_id]
        rows.append(evaluate(page, "tesseract-5.5-eng-psm3", run_tesseract(path)))
        rows.append(evaluate(page, "paddleocr-3.7-ppocrv6-en", run_paddle(paddle, path)))
    peak_memory_mb = process.memory_info().rss / 1024 / 1024
    stable_payload = {
        "schema": SCHEMA,
        "dataset": {"id": DATASET_ID, "revision": pinned_revision, "annotation_file": ANNOTATION_FILE, "annotation_sha256": sha256_file(annotation_path), "selected_pages": [page.page_id for page in selected]},
        "input_manifest": input_manifest,
        "rows": rows,
        "aggregate": aggregate(rows),
        "denominators": {"pages": len(selected), "engines": 2, "page_engine_pairs": len(rows)},
        "constraints": {"external_spend_usd": 0, "gcloud_used": False, "paid_api_used": False, "gpu_used": False},
    }
    stable_sha = sha256_bytes(canonical_json(stable_payload).encode("utf-8"))
    report = {
        **stable_payload,
        "stable_payload_sha256": stable_sha,
        "environment": {
            "platform": platform.platform(), "python": sys.version.split()[0],
            "packages": package_versions(["paddleocr", "paddlepaddle", "huggingface-hub", "pytesseract", "Pillow", "opencv-python-headless", "psutil"]),
            "tesseract": tesseract_identity(), "paddle_model_cache": model_cache_identity(), "peak_rss_mb": peak_memory_mb,
        },
    }
    return report


def write_report(report: Mapping[str, Any], output_dir: Path) -> Path:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "canary.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (reports_dir / "canary.sha256").write_text(f"{sha256_file(path)}  canary.json\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_sota_real_canary_v2/run"))
    parser.add_argument("--revision")
    args = parser.parse_args()
    if not 2 <= args.pages <= 20:
        raise SystemExit("--pages must be between 2 and 20")
    report = build_report(args.pages, args.output_dir, args.revision)
    path = write_report(report, args.output_dir)
    print(json.dumps({"report": str(path), "stable_payload_sha256": report["stable_payload_sha256"], "aggregate": report["aggregate"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
