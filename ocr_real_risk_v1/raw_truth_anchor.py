"""Build URL-bound numeric anchors from frozen raw OCDS releases.

The anchor source is independent of the PDF text layer used as visual ground
truth.  For each public document URL, this module collects canonical numbers
from structured metadata in the same OCDS release plus that document's own
metadata. URLs, source links and date fields are excluded from numeric parsing
to prevent path digits or concatenated timestamps from acting as truth.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .core import (
    canonical_truth,
    document_nodes,
    iter_source_lines,
    normalized_url,
    sha256_file,
)
from .truth_anchor import canonical_anchor_number

SCHEMA = "ocr-real-risk-raw-ocds-anchor/1"
RAW_NUMBER_RE = re.compile(
    r"(?<!\d)\d[\d\s.,:/-]{2,}\d(?!\d)|(?<!\d)\d{4,24}(?!\d)"
)
_EXCLUDED_KEYS = frozenset(
    {
        "documents",
        "url",
        "uri",
        "sources",
        "date",
        "datepublished",
        "datesigned",
        "startdate",
        "enddate",
        "lastmodified",
    }
)
_DOCUMENT_FIELDS = (
    "id",
    "title",
    "description",
    "documentType",
    "format",
    "language",
)


def _numbers_from_text(value: str) -> set[str]:
    result: set[str] = set()
    for match in RAW_NUMBER_RE.finditer(value or ""):
        anchor = canonical_anchor_number(match.group(0))
        if anchor is not None:
            result.add(anchor)
    return result


def _numbers_from_scalar(value: object) -> set[str]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, int):
        anchor = canonical_anchor_number(str(abs(value)))
        return {anchor} if anchor is not None else set()
    if isinstance(value, float):
        if not math.isfinite(value):
            return set()
        # Integer parts are useful for structured amounts and quantities;
        # decimal punctuation itself is outside the measured OCR token scope.
        anchor = canonical_anchor_number(str(abs(int(value))))
        return {anchor} if anchor is not None else set()
    return _numbers_from_text(str(value))


def iter_structured_scalars(
    value: object,
    *,
    parent_key: str = "",
) -> Iterator[object]:
    """Yield non-URL, non-date, non-document scalar metadata recursively."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).casefold().replace("_", "")
            if normalized_key in _EXCLUDED_KEYS:
                continue
            yield from iter_structured_scalars(
                child,
                parent_key=normalized_key,
            )
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from iter_structured_scalars(
                child,
                parent_key=parent_key,
            )
        return
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        yield value


def release_common_anchors(release: Mapping[str, Any]) -> set[str]:
    anchors: set[str] = set()
    for scalar in iter_structured_scalars(release):
        anchors.update(_numbers_from_scalar(scalar))
    return anchors


def document_specific_anchors(document: Mapping[str, Any]) -> set[str]:
    anchors: set[str] = set()
    for field in _DOCUMENT_FIELDS:
        anchors.update(_numbers_from_scalar(document.get(field)))
    return anchors


def build_raw_url_anchor_map(
    source_paths: Sequence[Path],
) -> tuple[dict[str, set[str]], dict[str, Any]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    release_count = document_references = pdf_references = 0
    releases_without_anchors = documents_without_anchors = 0
    document_type_counts: Counter[str] = Counter()

    for source_path in source_paths:
        for _line_number, release in iter_source_lines(source_path):
            release_count += 1
            common = release_common_anchors(release)
            if not common:
                releases_without_anchors += 1
            for document in document_nodes(release):
                document_references += 1
                url = normalized_url(str(document.get("url") or "").strip())
                if not url or ".pdf" not in url.casefold().split("?", 1)[0]:
                    continue
                pdf_references += 1
                document_type_counts[
                    str(document.get("documentType") or "unknown")
                ] += 1
                anchors = common | document_specific_anchors(document)
                if not anchors:
                    documents_without_anchors += 1
                    continue
                mapping[url].update(anchors)

    result = dict(mapping)
    census = {
        "schema": SCHEMA,
        "source_files": {
            str(path): sha256_file(path) for path in source_paths
        },
        "releases": release_count,
        "document_references": document_references,
        "pdf_references": pdf_references,
        "urls_with_anchors": len(result),
        "unique_url_anchor_pairs": sum(len(values) for values in result.values()),
        "releases_without_anchors": releases_without_anchors,
        "documents_without_anchors": documents_without_anchors,
        "document_type_counts": dict(sorted(document_type_counts.items())),
        "excluded_metadata": sorted(_EXCLUDED_KEYS),
        "anchor_length": "4-24 digits; years and repeated-digit junk excluded",
        "measured_pdf_truth_length": "unchanged at 4-12 digits",
    }
    return result, census


def anchored_native_truths(
    url: str,
    native_tokens: Iterable[str],
    anchor_map: Mapping[str, set[str]],
) -> list[str]:
    anchors = anchor_map.get(normalized_url(url), set())
    result: list[str] = []
    for token in native_tokens:
        truth = canonical_truth(token)
        if truth is not None and truth in anchors:
            result.append(truth)
    return result
