"""Dual-source anchors for trustworthy numeric OCR ground truth.

A PDF text-layer token is eligible only when the same canonical number also
appears in the frozen OCDS record that selected the document. This does not
make the observations statistically independent, but it prevents an
unanchored or corrupt hidden text layer from becoming the sole oracle.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .core import canonical_truth, normalized_url


SCHEMA = "ocr-real-risk-truth-anchor/1"
RAW_NUMBER_RE = re.compile(
    r"(?<!\d)\d[\d\s.,:/-]{2,}\d(?!\d)|(?<!\d)\d{4,24}(?!\d)"
)
ANCHOR_DIGIT_RE = re.compile(r"^\d{4,24}$")
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def canonical_anchor_number(value: str) -> str | None:
    """Canonicalize structured identifiers without widening OCR truth scope.

    Source records may contain long invoice or payment identifiers such as
    ``000-001-01-00000524``. They are useful anchors even though the measured
    OCR token protocol remains restricted to 4–12 digits by ``canonical_truth``.
    """
    compact = re.sub(r"\D", "", value or "")
    if not ANCHOR_DIGIT_RE.fullmatch(compact):
        return None
    if YEAR_RE.fullmatch(compact):
        return None
    if len(set(compact)) == 1 and len(compact) >= 6:
        return None
    return compact


def anchored_numbers(value: str) -> set[str]:
    numbers: set[str] = set()
    for match in RAW_NUMBER_RE.finditer(value or ""):
        anchor = canonical_anchor_number(match.group(0))
        if anchor is not None:
            numbers.add(anchor)
    return numbers


def build_url_anchor_map(
    source_path: Path,
) -> tuple[dict[str, set[str]], dict[str, int]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    source_records = invalid_lines = document_references = 0
    for raw_line in source_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        source_records += 1
        record_text_parts = [
            str(record.get("oncae_object_text") or ""),
            str(record.get("shared_code") or ""),
            str(record.get("ocid_oncae") or ""),
        ]
        documents = record.get("oncae_documents") or []
        for document in documents:
            if not isinstance(document, dict):
                continue
            url = normalized_url(str(document.get("url") or ""))
            if not url:
                continue
            document_references += 1
            text = " | ".join(
                [
                    *record_text_parts,
                    str(document.get("title") or ""),
                    str(document.get("description") or ""),
                    str(document.get("documentType") or ""),
                    urllib.parse.unquote(
                        Path(urllib.parse.urlsplit(url).path).name
                    ),
                ]
            )
            mapping[url].update(anchored_numbers(text))
    return dict(mapping), {
        "source_records": source_records,
        "invalid_json_lines": invalid_lines,
        "document_references": document_references,
        "urls_with_anchors": sum(bool(values) for values in mapping.values()),
        "unique_urls": len(mapping),
        "unique_url_number_pairs": sum(len(values) for values in mapping.values()),
    }


def eligible_native_truths(
    url: str,
    native_tokens: Iterable[str],
    anchor_map: dict[str, set[str]],
) -> list[str]:
    anchors = anchor_map.get(normalized_url(url), set())
    result: list[str] = []
    for token in native_tokens:
        truth = canonical_truth(token)
        if truth is not None and truth in anchors:
            result.append(truth)
    return result
