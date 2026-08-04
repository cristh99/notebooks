"""Pure all-page native-text indexing helpers."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .core import MIN_NATIVE_WORDS, canonical_json, sha256_bytes

SCHEMA = "ocr-real-risk-full-native-index/1"
MAX_NATIVE_INDEX_PAGES = 600


@dataclass(frozen=True)
class IndexedPage:
    page_number: int
    width_pt: float
    height_pt: float
    words: tuple[dict[str, object], ...]

    @property
    def native_word_count(self) -> int:
        return sum(bool(str(word.get("text") or "").strip()) for word in self.words)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_bbox_document(path: Path) -> list[IndexedPage]:
    root = ET.parse(path).getroot()
    pages: list[IndexedPage] = []
    nodes = (node for node in root.iter() if _local_name(node.tag) == "page")
    for page_number, page in enumerate(nodes, start=1):
        width = float(page.attrib.get("width", "0") or 0)
        height = float(page.attrib.get("height", "0") or 0)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"invalid page geometry: {page_number}")
        words: list[dict[str, object]] = []
        for word in page.iter():
            if _local_name(word.tag) != "word":
                continue
            text = "".join(word.itertext()).strip()
            try:
                bbox = [
                    float(word.attrib["xMin"]),
                    float(word.attrib["yMin"]),
                    float(word.attrib["xMax"]),
                    float(word.attrib["yMax"]),
                ]
            except (KeyError, TypeError, ValueError):
                continue
            if bbox[2] > bbox[0] and bbox[3] > bbox[1]:
                words.append({"text": text, "bbox_pt": bbox})
        pages.append(IndexedPage(page_number, width, height, tuple(words)))
    if not pages:
        raise RuntimeError("native index has no pages")
    if len(pages) > MAX_NATIVE_INDEX_PAGES:
        raise RuntimeError("native index page limit exceeded")
    return pages


def location_selection_key(
    source_sha256: str,
    page_number: int,
    bbox_pt: Sequence[float],
    truth: str,
) -> str:
    payload = {
        "source_sha256": source_sha256,
        "page_number": int(page_number),
        "bbox_pt": [round(float(value), 4) for value in bbox_pt],
        "truth": truth,
    }
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _same_location(
    word: Mapping[str, object],
    selected: Mapping[str, object],
    canonicalizer: Callable[[str], str | None],
) -> bool:
    truth = canonicalizer(str(word.get("text") or ""))
    if truth != selected.get("truth"):
        return False
    try:
        observed = tuple(round(float(value), 4) for value in word["bbox_pt"])
        expected = tuple(round(float(value), 4) for value in selected["bbox_pt"])
    except (KeyError, TypeError, ValueError):
        return False
    return observed == expected


def isolate_selected_location(
    page: IndexedPage,
    selected: Mapping[str, object],
    canonicalizer: Callable[[str], str | None],
) -> list[dict[str, object]]:
    """Leave exactly one eligible numeric word while preserving page word count."""
    if int(selected["page_number"]) != page.page_number:
        raise ValueError("selected location belongs to another page")
    isolated: list[dict[str, object]] = []
    matches = 0
    for word in page.words:
        copied = dict(word)
        truth = canonicalizer(str(word.get("text") or ""))
        if _same_location(word, selected, canonicalizer):
            copied["text"] = str(selected["truth"])
            matches += 1
        elif truth is not None:
            copied["text"] = ""
        isolated.append(copied)
    if matches != 1:
        raise RuntimeError(f"selected native location matched {matches} words")
    return isolated


def select_dual_anchored_location(
    source_sha256: str,
    pages: Iterable[IndexedPage],
    anchors: set[str],
    canonicalizer: Callable[[str], str | None],
    *,
    minimum_native_words: int = MIN_NATIVE_WORDS,
) -> tuple[dict[str, object] | None, dict[str, int]]:
    candidates: list[dict[str, object]] = []
    metrics = {
        "pages_indexed": 0,
        "pages_below_native_word_floor": 0,
        "pages_with_dual_candidates": 0,
        "native_words_indexed": 0,
        "numeric_words_in_scope": 0,
        "dual_anchored_words": 0,
        "dual_candidate_locations": 0,
    }
    for page in pages:
        metrics["pages_indexed"] += 1
        metrics["native_words_indexed"] += page.native_word_count
        if page.native_word_count < minimum_native_words:
            metrics["pages_below_native_word_floor"] += 1
            continue
        found_on_page = 0
        for word in page.words:
            truth = canonicalizer(str(word.get("text") or ""))
            if truth is None:
                continue
            metrics["numeric_words_in_scope"] += 1
            if truth not in anchors:
                continue
            metrics["dual_anchored_words"] += 1
            found_on_page += 1
            bbox = [float(value) for value in word["bbox_pt"]]
            candidates.append(
                {
                    "page_number": page.page_number,
                    "page_width_pt": page.width_pt,
                    "page_height_pt": page.height_pt,
                    "native_word_count": page.native_word_count,
                    "truth": truth,
                    "bbox_pt": bbox,
                    "selection_rank_sha256": location_selection_key(
                        source_sha256, page.page_number, bbox, truth
                    ),
                }
            )
        if found_on_page:
            metrics["pages_with_dual_candidates"] += 1
    candidates.sort(
        key=lambda row: (
            str(row["selection_rank_sha256"]),
            int(row["page_number"]),
            tuple(float(value) for value in row["bbox_pt"]),
        )
    )
    metrics["dual_candidate_locations"] = len(candidates)
    return (candidates[0] if candidates else None), metrics
