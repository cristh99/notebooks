"""Execute the real OCR holdout with dual-source numeric truth.

A native PDF numeric token remains eligible only when the same canonical number
is present in frozen raw OCDS metadata bound to that document URL. The wrapper
preserves all non-numeric native words for page-quality gates, but blanks
unanchored numeric words before the existing pre-OCR hash selection.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import evaluate as base
from .core import Candidate, canonical_json, canonical_truth, normalized_url, sha256_bytes
from .raw_truth_anchor import build_raw_url_anchor_map


def filter_words_by_anchor(
    words: Sequence[Mapping[str, Any]],
    anchors: set[str],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Preserve page word count while excluding unanchored numeric truths."""
    result: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for word in words:
        copied = dict(word)
        truth = canonical_truth(str(word.get("text") or ""))
        if truth is None:
            counts["non_numeric_words_preserved"] += 1
        elif truth in anchors:
            counts["anchored_numeric_words"] += 1
        else:
            copied["text"] = ""
            counts["unanchored_numeric_words_excluded"] += 1
        result.append(copied)
    return result, counts


def execute_dual_anchor(
    candidates: Sequence[Candidate],
    output_dir: Path,
    max_documents: int,
    target_tokens: int,
    stage: str,
    source_paths: Sequence[Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    anchor_map, anchor_census = build_raw_url_anchor_map(source_paths)
    anchors_by_document_id = {
        candidate.key[:16]: set(
            anchor_map.get(normalized_url(candidate.url), set())
        )
        for candidate in candidates
    }
    anchor_payload = {
        url: sorted(values) for url, values in sorted(anchor_map.items())
    }
    anchor_map_sha256 = sha256_bytes(
        canonical_json(anchor_payload).encode("utf-8")
    )
    filter_counts: Counter[str] = Counter()
    original_extract_word_boxes = base.extract_word_boxes

    def anchored_extract_word_boxes(pdf, page_number, work):
        page_width, page_height, words = original_extract_word_boxes(
            pdf,
            page_number,
            work,
        )
        document_id = Path(work).name
        anchors = anchors_by_document_id.get(document_id, set())
        if anchors:
            filter_counts["pages_with_url_anchors"] += 1
        else:
            filter_counts["pages_without_url_anchors"] += 1
        filtered, counts = filter_words_by_anchor(words, anchors)
        filter_counts.update(counts)
        return page_width, page_height, filtered

    base.extract_word_boxes = anchored_extract_word_boxes
    try:
        report = base.execute(
            candidates,
            output_dir,
            max_documents,
            target_tokens,
            stage,
        )
    finally:
        base.extract_word_boxes = original_extract_word_boxes

    report["protocol"]["ground_truth"] = (
        "word-level PDF text coordinates AND the same canonical number in "
        "frozen raw OCDS metadata bound to the document URL"
    )
    report["protocol"]["dual_source_anchor"] = {
        "required": True,
        "anchor_schema": anchor_census["schema"],
        "anchor_map_sha256": anchor_map_sha256,
        "url_binding": "normalized public document URL",
        "excluded_metadata": anchor_census["excluded_metadata"],
        "pdf_truth_length": anchor_census["measured_pdf_truth_length"],
        "anchor_length": anchor_census["anchor_length"],
        "selection_before_ocr": True,
    }
    report["execution"]["dual_source_anchor_filter"] = {
        **dict(sorted(filter_counts.items())),
        "candidate_urls_with_anchors": sum(
            bool(anchors_by_document_id.get(candidate.key[:16], set()))
            for candidate in candidates
        ),
        "candidate_urls_without_anchors": sum(
            not anchors_by_document_id.get(candidate.key[:16], set())
            for candidate in candidates
        ),
    }
    report["anchor_census"] = anchor_census
    report.pop("stable_payload_sha256", None)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )
    return report, anchor_census
