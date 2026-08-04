"""Execute the real OCR holdout with dual-source numeric truth.

A native PDF numeric token remains eligible only when the same canonical number
is present in frozen raw OCDS metadata bound to that document URL. All sampling
choices in this module are metadata-only or page-count-only and occur before
OCR: one document per process, a born-digital document-type scope, and fixed
quantile pages. Unanchored numeric words are blanked before the existing
pre-OCR hash selection while non-numeric words remain available to page-quality
gates.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import evaluate as base
from .core import (
    Candidate,
    canonical_json,
    canonical_truth as canonical_plain_truth,
    normalized_url,
    sha256_bytes,
)
from .raw_truth_anchor import build_raw_url_anchor_map

VECTOR_TRUTH_DOCUMENT_PRIORITY = {
    "biddingDocuments": 0,
    "technicalSpecifications": 0,
    "clarifications": 1,
    "amendment": 1,
    "solicitationDocumentAnnexe": 2,
    "tenderNotice": 2,
    "awardNotice": 3,
    "evaluationReports": 3,
    "recordOpeningTendersReceived": 4,
}
VECTOR_TRUTH_DOCUMENT_TYPES = frozenset(VECTOR_TRUTH_DOCUMENT_PRIORITY)
_CURRENCY_PREFIX_RE = re.compile(
    r"^(?:HNL|LPS?|L\.?|US\$|\$)\s*",
    re.IGNORECASE,
)
_EN_GROUPED_RE = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?$")
_ES_GROUPED_RE = re.compile(r"^\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?$")
_DECIMAL_RE = re.compile(r"^\d{4,10}[.,]\d{1,2}$")


def canonical_dual_truth(text: str) -> str | None:
    """Canonicalize plain digits and grouped monetary tokens, not dates/IDs."""
    plain = canonical_plain_truth(text)
    if plain is not None:
        return plain
    value = _CURRENCY_PREFIX_RE.sub("", (text or "").strip())
    value = value.strip(";:()[]{}")
    if not (
        _EN_GROUPED_RE.fullmatch(value)
        or _ES_GROUPED_RE.fullmatch(value)
        or _DECIMAL_RE.fullmatch(value)
    ):
        return None
    compact = value.replace(",", "").replace(".", "")
    if not 4 <= len(compact) <= 12 or not compact.isdigit():
        return None
    if len(set(compact)) == 1 and len(compact) >= 6:
        return None
    return compact


def quantile_pages(page_count: int, maximum_pages: int = 8) -> tuple[int, ...]:
    """Select fixed page-count quantiles without inspecting text or OCR."""
    if page_count <= 0:
        raise ValueError("page_count must be positive")
    if maximum_pages <= 0:
        raise ValueError("maximum_pages must be positive")
    if page_count <= maximum_pages:
        return tuple(range(1, page_count + 1))
    pages = {
        round(1 + index * (page_count - 1) / (maximum_pages - 1))
        for index in range(maximum_pages)
    }
    pages.update((1, page_count))
    return tuple(sorted(max(1, min(page_count, page)) for page in pages))


def prepare_process_disjoint_candidates(
    candidates: Sequence[Candidate],
) -> tuple[list[Candidate], dict[str, Any]]:
    """Keep one born-digital candidate per process using metadata only."""
    eligible = [
        candidate
        for candidate in candidates
        if candidate.document_type in VECTOR_TRUTH_DOCUMENT_TYPES
    ]
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in eligible:
        process = candidate.process or candidate.ocid or candidate.url
        grouped[process].append(candidate)
    selected: list[Candidate] = []
    for rows in grouped.values():
        rows.sort(
            key=lambda candidate: (
                VECTOR_TRUTH_DOCUMENT_PRIORITY[candidate.document_type],
                candidate.key,
            )
        )
        selected.append(rows[0])
    selected.sort(
        key=lambda candidate: (
            VECTOR_TRUTH_DOCUMENT_PRIORITY[candidate.document_type],
            candidate.key,
        )
    )
    return selected, {
        "input_candidates": len(candidates),
        "excluded_out_of_vector_truth_scope": len(candidates) - len(eligible),
        "eligible_document_references": len(eligible),
        "unique_processes": len(grouped),
        "selected_process_disjoint_documents": len(selected),
        "allowed_document_types": sorted(VECTOR_TRUTH_DOCUMENT_TYPES),
        "document_type_priority": VECTOR_TRUTH_DOCUMENT_PRIORITY,
        "selection_uses_ocr": False,
    }


def filter_words_by_anchor(
    words: Sequence[Mapping[str, Any]],
    anchors: set[str],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Preserve page word count while excluding unanchored numeric truths."""
    result: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for word in words:
        copied = dict(word)
        truth = canonical_dual_truth(str(word.get("text") or ""))
        if truth is None:
            counts["non_numeric_words_preserved"] += 1
        elif truth in anchors:
            copied["text"] = truth
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
    prepared_candidates, selection_census = prepare_process_disjoint_candidates(
        candidates
    )
    anchor_map, anchor_census = build_raw_url_anchor_map(source_paths)
    anchors_by_document_id = {
        candidate.key[:16]: set(
            anchor_map.get(normalized_url(candidate.url), set())
        )
        for candidate in prepared_candidates
    }
    anchor_payload = {
        url: sorted(values) for url, values in sorted(anchor_map.items())
    }
    anchor_map_sha256 = sha256_bytes(
        canonical_json(anchor_payload).encode("utf-8")
    )
    filter_counts: Counter[str] = Counter()
    original_extract_word_boxes = base.extract_word_boxes
    original_selected_pages = base.selected_pages
    original_canonical_truth = base.canonical_truth

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
    base.selected_pages = quantile_pages
    base.canonical_truth = canonical_dual_truth
    try:
        report = base.execute(
            prepared_candidates,
            output_dir,
            max_documents,
            target_tokens,
            stage,
        )
    finally:
        base.extract_word_boxes = original_extract_word_boxes
        base.selected_pages = original_selected_pages
        base.canonical_truth = original_canonical_truth

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
        "pdf_truth_length": "4-12 digits after declared numeric formatting normalization",
        "anchor_length": anchor_census["anchor_length"],
        "selection_before_ocr": True,
    }
    report["protocol"]["numeric_format_scope"] = {
        "plain_digits": True,
        "grouped_thousands": True,
        "decimal_fraction_digits": "1-2",
        "hyphenated_or_slash_identifiers": False,
        "years": False,
    }
    report["protocol"]["page_selection"] = {
        "method": "fixed page-count quantiles",
        "maximum_pages_per_document": 8,
        "uses_text_or_ocr": False,
    }
    report["protocol"]["document_scope"] = selection_census
    report["execution"]["dual_source_anchor_filter"] = {
        **dict(sorted(filter_counts.items())),
        "candidate_urls_with_anchors": sum(
            bool(anchors_by_document_id.get(candidate.key[:16], set()))
            for candidate in prepared_candidates
        ),
        "candidate_urls_without_anchors": sum(
            not anchors_by_document_id.get(candidate.key[:16], set())
            for candidate in prepared_candidates
        ),
    }
    report["execution"]["process_disjoint_selection"] = selection_census
    report["anchor_census"] = anchor_census
    report.pop("stable_payload_sha256", None)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )
    return report, anchor_census
