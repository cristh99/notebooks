"""Compatibility wrapper for current OmniDocBench and Paddle CPU inference."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import pytesseract

from . import run_canary as core


def select_pages(raw_pages: Sequence[Mapping[str, Any]], count: int):
    pages = []
    for raw in raw_pages:
        try:
            page = core.ground_truth_from_page(raw)
        except (TypeError, ValueError):
            continue
        if page.language.casefold() not in {"en", "english"} or len(page.text) < 120 or not page.boxes:
            continue
        pages.append(page)
    if len(pages) < count:
        raise RuntimeError(f"only {len(pages)} eligible English pages; need {count}")
    pages.sort(key=lambda item: core.sha256_bytes(item.image_path.encode("utf-8")))
    selectors = [
        lambda page: page.has_table,
        lambda page: page.has_formula,
        lambda page: page.fuzzy_scan,
        lambda page: page.layout in {"double_column", "three_column", "1andmore_column"},
        lambda page: page.domain == "note",
        lambda page: not page.has_table and not page.has_formula and not page.fuzzy_scan,
    ]
    selected, used = [], set()
    for predicate in selectors:
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
            return selected
    raise AssertionError("selection denominator drift")


def make_paddle_engine() -> Any:
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang="en",
        ocr_version="PP-OCRv6",
        device="cpu",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def parse_paddle_result(result_items: Iterable[Any]) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    raw_shapes: list[str] = []
    for item in result_items:
        mapping = core._mapping_from_result(item)
        raw_shapes.append(",".join(sorted(str(key) for key in mapping.keys())))
        texts = core._find_key(mapping, "rec_texts")
        if texts is None:
            texts = core._find_key(mapping, "texts")
        polygons = core._find_key(mapping, "rec_polys")
        if polygons is None:
            polygons = core._find_key(mapping, "dt_polys")
        if polygons is None:
            polygons = core._find_key(mapping, "polys")
        scores = core._find_key(mapping, "rec_scores")
        if scores is None:
            scores = core._find_key(mapping, "scores")
        if texts is None or polygons is None:
            continue
        texts = list(texts)
        polygons = list(polygons)
        scores = list(scores) if scores is not None else [None] * len(texts)
        if len(texts) != len(polygons):
            raise ValueError("PaddleOCR text/polygon denominator mismatch")
        for index, (text, polygon) in enumerate(zip(texts, polygons, strict=True)):
            clean = core.normalize_text(str(text))
            if not clean:
                continue
            score = scores[index] if index < len(scores) else None
            lines.append(
                {
                    "text": clean,
                    "bbox": list(core.bbox_from_poly(polygon)),
                    "confidence": None if score is None else float(score),
                }
            )
    if not lines:
        raise RuntimeError(
            f"PaddleOCR produced no parseable lines; result keys={raw_shapes}"
        )
    lines.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return {
        "text": "\n".join(item["text"] for item in lines),
        "lines": lines,
        "result_keys": raw_shapes,
    }


_original_evaluate = core.evaluate


def evaluate(gt: Any, engine: str, prediction: Mapping[str, Any]) -> dict[str, Any]:
    if engine == "tesseract-5.5-eng-psm3":
        engine = f"tesseract-{pytesseract.get_tesseract_version()}-eng-psm3"
    return _original_evaluate(gt, engine, prediction)


core.select_pages = select_pages
core.make_paddle_engine = make_paddle_engine
core.parse_paddle_result = parse_paddle_result
core.evaluate = evaluate

if __name__ == "__main__":
    core.main()
