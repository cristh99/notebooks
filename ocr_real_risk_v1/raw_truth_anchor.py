"""Build URL-bound numeric anchors from frozen raw OCDS releases.

The anchor source is independent of the PDF text layer used as visual ground
truth. For each public document URL, this module collects canonical numbers
from structured metadata in the same OCDS release plus that document's own
metadata. URLs, source links and date fields are excluded from numeric parsing
to prevent path digits or concatenated timestamps from acting as truth.

Structured numeric scalars and PDF-formatted amounts share one representation:
integer values may appear either without decimals or with an equivalent ``.00``;
non-integer values preserve their exact one- or two-digit fractional part. This
prevents ``9,158,922.75`` in a PDF from being compared with the incompatible
integer-only anchor ``9158922``.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
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

SCHEMA = "ocr-real-risk-raw-ocds-anchor/2"
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


def _validated_anchor(value: str) -> set[str]:
    anchor = canonical_anchor_number(value)
    return {anchor} if anchor is not None else set()


def _numbers_from_text(value: str) -> set[str]:
    result: set[str] = set()
    for match in RAW_NUMBER_RE.finditer(value or ""):
        result.update(_validated_anchor(match.group(0)))
    return result


def _decimal_scalar_variants(value: int | float) -> set[str]:
    """Return exact display-equivalent digit strings for a numeric scalar."""
    if isinstance(value, float) and not math.isfinite(value):
        return set()
    try:
        decimal_value = Decimal(str(abs(value)))
    except (InvalidOperation, ValueError):
        return set()
    if not decimal_value.is_finite():
        return set()

    integral = decimal_value.to_integral_value()
    if decimal_value == integral:
        integer_text = format(integral, "f").split(".", 1)[0]
        result = _validated_anchor(integer_text)
        result.update(_validated_anchor(f"{integer_text}00"))
        return result

    normalized = decimal_value.normalize()
    fraction_digits = max(0, -normalized.as_tuple().exponent)
    if fraction_digits < 1 or fraction_digits > 2:
        return set()
    minimal = format(normalized, "f").replace(".", "")
    result = _validated_anchor(minimal)
    if fraction_digits == 1:
        padded = format(decimal_value, ".2f").replace(".", "")
        result.update(_validated_anchor(padded))
    return result


def _numbers_from_scalar(value: object) -> set[str]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return _decimal_scalar_variants(value)
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
        "structured_numeric_normalization": (
            "integers: N and exact N.00; non-integers: exact 1-2 fractional digits"
        ),
        "measured_pdf_truth_length": "4-12 canonical digits",
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
