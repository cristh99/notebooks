from __future__ import annotations

import argparse
import ast
import csv
import difflib
import json
import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import duckdb
import psycopg2
from bson import decode_all

CVE_RE = re.compile(r"CVE[^0-9]*(\d{4})[^0-9]+([0-9]{1,8})", re.IGNORECASE)
DATE_RE = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
YEAR_RE = re.compile(r"\b(18\d{2}|19\d{2}|20[0-2]\d)\b")

_CVE_PREFIX_RE = re.compile(
    r"^(?:nvd|kev|cpe|mongo|xref|mirror|feed|catalog|row|doc|scan|idx|ref|blob|join|link)"
    r"-[a-p]{5}(?:::key=|::id=|::ref=|::|=>|__|--|~~|\+\+|[|/#@~$%])",
    re.IGNORECASE,
)
_CVE_SUFFIX_RE = re.compile(
    r"(?:::end=|::aux=|::via=|::|=>|__|--|~~|\+\+|[|/#@~$%])"
    r"(?:tail|src|seen|frag|node|sink|cache|slot|mark|trace|batch|edge|note|leaf|tag|trail)"
    r"-[a-p]{4}$",
    re.IGNORECASE,
)
_CVE_LEFT_WRAPPER_RE = re.compile(
    r"^(?:(?:ctx|raw|join|id|key|slot|doc):|[\[({<])?[a-p]{3}(?:::|:|[|~/#@])?",
    re.IGNORECASE,
)
_CVE_RIGHT_WRAPPER_RE = re.compile(
    r"(?:(?:\]|\)|\}|>|:ctx|:raw|:join|:id|:key|:slot|:doc))?[a-p]{3}$",
    re.IGNORECASE,
)
_CVE_NOISE_MARKS = set("@#$%~&!?")
_OCR_TO_DIGIT = str.maketrans({"O": "0", "I": "1", "Z": "2", "S": "5", "G": "6", "B": "8", "o": "0", "i": "1", "z": "2", "s": "5", "g": "6", "b": "8"})

_ID_WORDS = (
    "piid", "piin", "acq", "award", "contract", "ref", "id", "no", "doc", "file", "rec", "txn",
    "obl", "oblig", "po", "to", "do", "mod", "sol", "proc", "purch", "inst", "agr", "grt", "acrn",
    "clin", "slin", "pr", "wbs", "cage", "uei", "order", "document", "reference", "identifier", "record",
    "transaction", "obligation", "solicitation", "procurement", "purchase", "agreement", "instrument",
    "requisition", "authorization", "modification", "delivery", "task", "grant", "cooperative", "awards",
    "contracts", "orders", "documents", "records",
)
_ID_WORD_ALT = "|".join(sorted(_ID_WORDS, key=len, reverse=True))
_ID_PREFIX_RE = re.compile(
    rf"^\s*(?:"
    rf"#{{1,2}}\s*|"
    rf"(?:{_ID_WORD_ALT})\s+(?:no\.\s+|#\s+)|"
    rf"(?:{_ID_WORD_ALT})(?:[_-](?:id|no))?\s*(?:[:=/]\s*|\.\s*|/\s*)"
    rf")",
    re.IGNORECASE,
)
_ID_PREFIX_TOKENS = tuple(sorted({
    *(_ID_WORDS),
    "awardno", "contractno", "refno", "docno", "orderno", "pono", "tono", "dono", "modno", "solno",
    "piidno", "awardid", "contractid", "orderid", "docid",
}, key=len, reverse=True))


@dataclass(frozen=True)
class Paths:
    dab_root: Path
    output_dir: Path


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_space(value).lower())


def _canonical_cve_parts(year: int, number: int) -> str | None:
    current_year = datetime.now().year + 1
    if not (1999 <= year <= current_year) or not (0 <= number <= 99_999_999):
        return None
    return f"CVE-{year:04d}-{number:04d}"


def _base36_int(value: str) -> int | None:
    try:
        return int(value, 36)
    except (TypeError, ValueError):
        return None


def _decode_cve_core(core: str) -> set[str]:
    results: set[str] = set()

    def add(year: int | str, number: int | str) -> None:
        try:
            canonical = _canonical_cve_parts(int(year), int(number))
        except (TypeError, ValueError):
            return
        if canonical:
            results.add(canonical)

    value = core.strip()
    match = CVE_RE.fullmatch(value)
    if match:
        add(match.group(1), match.group(2))
    for pattern in (
        r"(?:CVE[-_:])?(\d{4})[-_:](\d{1,8})",
        r"(\d{4})::(\d{1,8})",
    ):
        match = re.fullmatch(pattern, value, re.I)
        if match:
            add(match.group(1), match.group(2))

    match = re.fullmatch(r"yr(-?\d+)_n(-?\d+)", value, re.I)
    if match:
        add(int(match.group(1)) + 1999, int(match.group(2)) - 17)
    match = re.fullmatch(r"n(-?\d+)_y(-?\d+)", value, re.I)
    if match:
        add(int(match.group(2)) + 1900, int(match.group(1)) - 100000)
    match = re.fullmatch(r"rv(\d{4})-(\d{1,8})", value, re.I)
    if match:
        add(match.group(1)[::-1], match.group(2)[::-1])
    match = re.fullmatch(r"b36y([0-9a-z]+)n([0-9a-z]+)", value, re.I)
    if match:
        year = _base36_int(match.group(1)); number = _base36_int(match.group(2))
        if year is not None and number is not None: add(year, number)
    match = re.fullmatch(r"h([0-9a-f]+)x([0-9a-f]+)", value, re.I)
    if match:
        add(int(match.group(1), 16), int(match.group(2), 16))
    match = re.fullmatch(r"ord(\d+)\.(\d+)", value, re.I)
    if match:
        add(int(match.group(1)) + 2000, int(match.group(2)))
    match = re.fullmatch(r"mx(\d{2})-(\d{1,2})-(\d{2})-(\d*)", value, re.I)
    if match:
        add(match.group(1) + match.group(3), match.group(2) + match.group(4))
    match = re.fullmatch(r"sp(\d{1,2})_(\d{2})_(\d*)_(\d{2})", value, re.I)
    if match:
        add(match.group(4) + match.group(2), match.group(1) + match.group(3))
    match = re.fullmatch(r"k(\d{4})(\d{7})", value, re.I)
    if match:
        add(match.group(1), int(match.group(2)))
    match = re.fullmatch(r"off(-?\d+)\.(-?\d+)", value, re.I)
    if match:
        add(int(match.group(1)) - 37, int(match.group(2)) - 7919)
    match = re.fullmatch(r"p(\d{2})(\d{2})\.(\d+)\.(\d+)", value, re.I)
    if match:
        year = int(match.group(3)) * 100 + int(match.group(1)); number = int(match.group(4))
        if number % 97 == int(match.group(2)): add(year, number)
    match = re.fullmatch(r"dot([0-9.]+)", value, re.I)
    if match:
        digits = match.group(1).replace(".", "")
        if len(digits) == 11: add(digits[:4], int(digits[4:]))

    match = re.fullmatch(r"ocr(.+)", value, re.I)
    if match:
        mapped_payload = match.group(1).translate(_OCR_TO_DIGIT)
        payload_match = re.fullmatch(r"CVE(\d{4})(\d{7})", mapped_payload, re.I)
        if payload_match:
            add(payload_match.group(1), int(payload_match.group(2)))
    match = re.fullmatch(r"ob(.+)", value, re.I)
    if match:
        mapped_payload = match.group(1).translate(_OCR_TO_DIGIT)
        payload_match = re.fullmatch(r"(\d{4})-(\d{1,8})", mapped_payload)
        if payload_match:
            add(payload_match.group(1), payload_match.group(2))

    match = re.fullmatch(r"i([0-9]{11})", value, re.I)
    if match:
        seq = match.group(1); add(seq[0] + seq[2] + seq[4] + seq[6], seq[1] + seq[3] + seq[5] + seq[7:])
    match = re.fullmatch(r"ri([0-9]{11})", value, re.I)
    if match:
        seq = match.group(1)
        add((seq[0] + seq[2] + seq[4] + seq[6])[::-1], (seq[1] + seq[3] + seq[5] + seq[7:])[::-1])
    match = re.fullmatch(r"b36mix([0-9a-z]+)_([0-9]{7})", value, re.I)
    if match:
        year = _base36_int(match.group(1))
        if year is not None: add(year + 1990, int(match.group(2)[::-1]))
    match = re.fullmatch(r"hexmix([0-9a-f]+)_(-?\d+)", value, re.I)
    if match:
        add(int(match.group(2)) + 1970, int(match.group(1), 16))
    match = re.fullmatch(r"win([+-]?\d+)/(\d+)", value, re.I)
    if match:
        transformed = int(match.group(2)) - 1
        if transformed % 3 == 0: add(int(match.group(1)) + 2010, transformed // 3)
    match = re.fullmatch(r"tri(\d+)-(\d+)", value, re.I)
    if match:
        y = int(match.group(1)) - 2; n = int(match.group(2)) - 4
        if y % 3 == 0 and n % 5 == 0: add(y // 3, n // 5)
    match = re.fullmatch(r"swap(\d{3})-(\d{4})-(\d{4})", value, re.I)
    if match:
        add(match.group(2), int(match.group(1) + match.group(3)))
    match = re.fullmatch(r"fold(\d{4})-(\d{7})", value, re.I)
    if match:
        first, second = match.groups(); add(first[:2] + second[:2], int(second[2:] + first[2:]))
    match = re.fullmatch(r"ocrx(.+)", value, re.I)
    if match:
        mapped_payload = match.group(1).translate(_OCR_TO_DIGIT)
        payload_match = re.fullmatch(r"(\d+)_([0-9]+)", mapped_payload)
        if payload_match:
            add(int(payload_match.group(1)) - 101, int(payload_match.group(2)) - 202)
    match = re.fullmatch(r"z([0-9a-z]+)\.(\d{4})", value, re.I)
    if match:
        total = _base36_int(match.group(1)); year = int(match.group(2)[::-1])
        if total is not None: add(year, total - year)
    return results


def _is_cve_noise_fragment(fragment: str) -> bool:
    mark = r"[@#$%~&!?]"
    patterns = (
        rf"{mark}[A-P]{{2}}[0-9a-z]{{3}}",
        rf"[0-9a-z]{{3}}{mark}[A-P]{{3}}",
        rf"[A-P]{{2}}{mark}\d{{3}}",
        rf"\d{{3}}{mark}[A-P]{{3}}",
        rf"[A-P]{{2}}{mark}[A-P]{{3}}",
        rf"[0-9a-z]{{3}}{mark}[A-P]{{2}}",
        rf"[A-P]{{2}}{mark}\d{{2}}",
        rf"[A-P]{{2}}\d{{2}}{mark}[A-P]",
        rf"[A-P]{{2}}{mark}\d{{3}}",
        rf"[A-P]{mark}[0-9a-z]{{3}}[A-P]",
        rf"\d{{2}}{mark}[A-P]{{2}}[0-9a-z]",
    )
    return any(re.fullmatch(pattern, fragment, re.I) for pattern in patterns)


def _cve_core_candidates(value: Any) -> list[str]:
    text = normalize_space(value)
    text = _CVE_PREFIX_RE.sub("", text, count=1)
    text = _CVE_SUFFIX_RE.sub("", text, count=1)
    text = _CVE_LEFT_WRAPPER_RE.sub("", text, count=1)
    text = _CVE_RIGHT_WRAPPER_RE.sub("", text, count=1)
    candidates = [text]
    positions = [index for index, char in enumerate(text) if char in _CVE_NOISE_MARKS]
    for position in positions:
        for length in (5, 6, 7):
            for start in range(max(0, position - length + 1), min(position, len(text) - length) + 1):
                fragment = text[start:start + length]
                if _is_cve_noise_fragment(fragment):
                    candidates.append(text[:start] + text[start + length:])
    return list(dict.fromkeys(candidates))


def cve_candidates(value: Any) -> set[str]:
    text = normalize_space(value)
    direct = CVE_RE.search(text)
    if direct:
        canonical = _canonical_cve_parts(int(direct.group(1)), int(direct.group(2)))
        if canonical:
            return {canonical}
    decoded: set[str] = set()
    for core in _cve_core_candidates(value):
        decoded.update(_decode_cve_core(core))
    return decoded


def canonical_cve(value: Any) -> str | None:
    decoded = cve_candidates(value)
    return next(iter(decoded)) if len(decoded) == 1 else None

def parse_date(value: Any) -> date | None:
    text = normalize_space(value)
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    match = DATE_RE.search(text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


_SMALL_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALE_NUMBERS = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def words_to_number(text: str) -> float | None:
    tokens = re.findall(r"[a-z]+", text.lower().replace("-", " "))
    if not tokens or not any(token in _SMALL_NUMBERS or token in _SCALE_NUMBERS for token in tokens):
        return None
    total = 0.0
    current = 0.0
    seen = False
    for token in tokens:
        if token in _SMALL_NUMBERS:
            current += _SMALL_NUMBERS[token]
            seen = True
        elif token == "hundred":
            current = max(current, 1.0) * 100.0
            seen = True
        elif token in {"thousand", "million", "billion"}:
            scale = float(_SCALE_NUMBERS[token])
            total += max(current, 1.0) * scale
            current = 0.0
            seen = True
    return total + current if seen else None


def parse_money(value: Any) -> float | None:
    text = normalize_space(value).lower()
    if not text:
        return None
    pieces = re.split(r"\s*(?:\+|\bplus\b|\band\b)\s*", text)
    if len(pieces) > 1:
        parsed = [parse_money(piece) for piece in pieces]
        if all(item is not None for item in parsed):
            return float(sum(item for item in parsed if item is not None))
    numeric = re.findall(
        r"(?<![a-z0-9])[-+]?\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*"
        r"(thousand|million|billion|mm|mil|[kmb])?",
        text,
    )
    if numeric:
        scales = {
            "k": 1_000.0, "thousand": 1_000.0,
            "m": 1_000_000.0, "mm": 1_000_000.0, "mil": 1_000_000.0, "million": 1_000_000.0,
            "b": 1_000_000_000.0, "billion": 1_000_000_000.0,
        }
        number, suffix = numeric[0]
        return float(number.replace(",", "")) * scales.get(suffix, 1.0)
    return words_to_number(text)


def identifier_signatures(value: Any, extra_prefixes: Sequence[str] = ()) -> set[str]:
    text = normalize_space(value)
    text = re.sub(r"(?i)[\s_.-]*OLD$", "", text)
    body = _ID_PREFIX_RE.sub("", text, count=1)
    compact = re.sub(r"[^A-Za-z0-9]+", "", body)
    if not compact:
        return set()
    candidates = {compact.lower(), compact.translate(_OCR_TO_DIGIT).lower()}
    prefixes = tuple(sorted({*extra_prefixes, *_ID_PREFIX_TOKENS}, key=len, reverse=True))
    for candidate in list(candidates):
        for prefix in prefixes:
            normalized_prefix = normalize_key(prefix)
            if normalized_prefix and candidate.startswith(normalized_prefix) and len(candidate) > len(normalized_prefix) + 2:
                stripped = candidate[len(normalized_prefix):]
                candidates.add(stripped)
                candidates.add(stripped.translate(_OCR_TO_DIGIT).lower())
    return {candidate for candidate in candidates if candidate}


def is_superseded_identifier(value: Any) -> bool:
    return bool(re.search(r"(?i)[\s_.-]*OLD$", normalize_space(value)))


def unique_signature_index(items: Iterable[tuple[Any, Any]], extra_prefixes: Sequence[str] = ()) -> tuple[dict[str, Any], set[str]]:
    index: dict[str, Any] = {}
    ambiguous: set[str] = set()
    for raw_id, payload in items:
        for signature in identifier_signatures(raw_id, extra_prefixes):
            if signature in index and index[signature] != payload:
                ambiguous.add(signature)
            else:
                index[signature] = payload
    for signature in ambiguous:
        index.pop(signature, None)
    return index, ambiguous


def fuzzy_signature_match(signatures: set[str], candidates: Mapping[str, Any], threshold: float = 0.9) -> Any | None:
    if not signatures or not candidates:
        return None
    best_score = threshold
    best_payload: Any | None = None
    tied = False
    for signature in signatures:
        bucket = [key for key in candidates if abs(len(key) - len(signature)) <= 2 and key and signature and key[0] == signature[0]]
        for key in bucket:
            score = difflib.SequenceMatcher(None, signature, key, autojunk=False).ratio()
            if score > best_score + 1e-12:
                best_score = score
                best_payload = candidates[key]
                tied = False
            elif abs(score - best_score) <= 1e-12 and candidates[key] != best_payload:
                tied = True
    return None if tied else best_payload

def pg_rows(dbname: str, query: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="postgres",
        dbname=dbname,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchall())
    finally:
        conn.close()


def sqlite_rows(path: Path, query: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(path)
    try:
        return list(conn.execute(query, params))
    finally:
        conn.close()


def duck_rows(path: Path, query: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    conn = duckdb.connect(str(path), read_only=True)
    try:
        return list(conn.execute(query, params).fetchall())
    finally:
        conn.close()


def bson_documents(path: Path) -> list[dict[str, Any]]:
    return [dict(item) for item in decode_all(path.read_bytes())]


def parse_project_records(content: str, fallback_date: date | None = None) -> tuple[date | None, list[dict[str, str]]]:
    text = content.replace("\r\n", "\n")
    report_date = parse_date(text) or fallback_date
    records: list[dict[str, str]] = []

    # Structured blocks: Project/Name, Type, Status appear on nearby lines.
    lines = [line.strip(" \t-*•") for line in text.splitlines() if line.strip()]
    current: dict[str, str] = {}
    key_patterns = {
        "project": re.compile(r"^(?:project(?:\s+name)?|name)\s*[:\-]\s*(.+)$", re.I),
        "type": re.compile(r"^(?:project\s+)?type\s*[:\-]\s*(.+)$", re.I),
        "status": re.compile(r"^(?:project\s+)?status\s*[:\-]\s*(.+)$", re.I),
    }
    for line in lines:
        matched = False
        for key, pattern in key_patterns.items():
            match = pattern.match(line)
            if not match:
                continue
            if key == "project" and current.get("project"):
                records.append(current)
                current = {}
            current[key] = normalize_space(match.group(1)).strip(".;")
            matched = True
            break
        if matched:
            continue
        # Single-line table-like records.
        match = re.search(
            r"project(?:\s+name)?\s*[:=]\s*(?P<project>.+?)\s*[|;,]\s*"
            r"(?:project\s+)?type\s*[:=]\s*(?P<type>.+?)\s*[|;,]\s*"
            r"(?:project\s+)?status\s*[:=]\s*(?P<status>.+?)(?:$|[|;])",
            line,
            re.I,
        )
        if match:
            records.append({key: normalize_space(value).strip(".;") for key, value in match.groupdict().items()})
    if current.get("project"):
        records.append(current)

    # Markdown/ASCII tables with project, type and status headers.
    for index, line in enumerate(lines):
        lower = line.lower()
        if "project" not in lower or "type" not in lower or "status" not in lower or "|" not in line:
            continue
        header = [normalize_space(cell).lower() for cell in line.strip("|").split("|")]
        try:
            p_idx = next(i for i, cell in enumerate(header) if "project" in cell or cell == "name")
            t_idx = next(i for i, cell in enumerate(header) if "type" in cell)
            s_idx = next(i for i, cell in enumerate(header) if "status" in cell)
        except StopIteration:
            continue
        for data_line in lines[index + 1 :]:
            if "|" not in data_line:
                break
            cells = [normalize_space(cell) for cell in data_line.strip("|").split("|")]
            if max(p_idx, t_idx, s_idx) >= len(cells) or all(set(cell) <= {"-", ":"} for cell in cells):
                continue
            records.append({"project": cells[p_idx], "type": cells[t_idx], "status": cells[s_idx]})
    deduped: dict[tuple[str, str, str], dict[str, str]] = {}
    for record in records:
        if not record.get("project"):
            continue
        key = (
            normalize_key(record.get("project")),
            normalize_key(record.get("type")),
            normalize_key(record.get("status")),
        )
        deduped[key] = record
    return report_date, list(deduped.values())


def canonical_project_key(value: Any) -> str:
    text = normalize_space(value)
    text = re.sub(r"\s*\((?:FEMA|CalJPIA|CalOES)\s+Project\)\s*$", "", text, flags=re.I)
    return normalize_key(text)

def solve_civic(paths: Paths) -> dict[str, Any]:
    root = paths.dab_root / "query_civic_unstructured" / "query_dataset"
    docs = bson_documents(root / "civic_docs_dump" / "civic_db" / "civic_docs.bson")
    cutoff = date(2023, 1, 1)
    latest: dict[str, tuple[date, str, str, str]] = {}
    for ordinal, doc in enumerate(docs):
        content = normalize_space(doc.get("report_content")) if "\n" not in str(doc.get("report_content", "")) else str(doc.get("report_content", ""))
        fallback = date(1900, 1, 1)
        report_id = normalize_space(doc.get("report_id"))
        digits = re.findall(r"\d+", report_id)
        if digits:
            fallback = date(1900, 1, min(28, int(digits[-1])))
        report_date, records = parse_project_records(content, fallback)
        if report_date is None or report_date > cutoff:
            continue
        for record in records:
            project = normalize_space(record.get("project"))
            key = canonical_project_key(project)
            candidate = (report_date, project, normalize_space(record.get("type")), normalize_space(record.get("status")))
            if key and (key not in latest or candidate[0] > latest[key][0]):
                latest[key] = candidate

    funding_rows = sqlite_rows(
        root / "funding.db",
        'SELECT project_name, grant_time, amount FROM "Funding"',
    )
    totals: dict[str, float] = defaultdict(float)
    names: dict[str, str] = {}
    for project_name, grant_time, amount in funding_rows:
        grant_date = parse_date(grant_time)
        if grant_date is None or grant_date > cutoff:
            continue
        key = canonical_project_key(project_name)
        names[key] = normalize_space(project_name)
        totals[key] += float(amount)

    qualifying: list[str] = []
    for key, (_, project, project_type, status) in latest.items():
        funding_key = key
        if funding_key not in totals:
            # Deterministic fuzzy fallback for punctuation/word-order noise.
            candidates = [candidate for candidate in totals if key in candidate or candidate in key]
            if len(candidates) == 1:
                funding_key = candidates[0]
        if normalize_key(project_type) == "capital" and normalize_key(status) == "design" and totals.get(funding_key, 0.0) > 500_000:
            qualifying.append(project or names.get(funding_key, funding_key))
    qualifying = sorted(set(qualifying), key=str.casefold)
    return {"projects": qualifying}


def solve_cve(paths: Paths) -> int:
    root = paths.dab_root / "query_cve" / "query_dataset"
    cve_rows = sqlite_rows(root / "vulns.db", "SELECT cve_id, published FROM cves")
    published_2023: set[str] = set()
    for raw, published in cve_rows:
        parsed = parse_date(published)
        if parsed and parsed.year == 2023:
            published_2023.update(cve_candidates(raw))
    kev_rows = pg_rows("cve_kev", "SELECT cve_ref FROM kev_entries")
    kev: set[str] = set()
    for (raw,) in kev_rows:
        kev.update(cve_candidates(raw))
    cpe_rows = duck_rows(
        root / "cpe.duckdb",
        """
        SELECT m.cve_id, m.vulnerable_flag
        FROM cpe_matches AS m
        JOIN vendor_aliases AS v
          ON lower(trim(v.alias)) = lower(trim(
            CASE
              WHEN starts_with(lower(m.criteria), 'cpe:2.3:a:') THEN split_part(m.criteria, ':', 4)
              WHEN strpos(m.criteria, '/') > 0 THEN split_part(m.criteria, '/', 1)
              ELSE split_part(m.criteria, ' ', 1)
            END
          ))
        WHERE lower(trim(v.canonical_vendor)) = 'apache'
        """,
    )
    truthy = {"1", "true", "yes", "y", "v", "affected", "vulnerable", "t"}
    apache_vulnerable: set[str] = set()
    for raw, vulnerable in cpe_rows:
        if normalize_key(vulnerable) in truthy:
            apache_vulnerable.update(cve_candidates(raw))
    return len(published_2023 & kev & apache_vulnerable)

def solve_stockindex(paths: Paths) -> dict[str, Any]:
    root = paths.dab_root / "query_stockindex" / "query_dataset"
    info_path = root / "indexInfo_query.db"
    trade_path = root / "indextrade_query.db"
    info_conn = sqlite3.connect(info_path)
    try:
        info_columns = [row[1] for row in info_conn.execute("PRAGMA table_info(index_info)")]
        info_rows = [dict(zip(info_columns, row)) for row in info_conn.execute("SELECT * FROM index_info")]
    finally:
        info_conn.close()
    trade_conn = duckdb.connect(str(trade_path), read_only=True)
    try:
        trade_columns = [row[1] for row in trade_conn.execute("PRAGMA table_info('index_trade')").fetchall()]
        trade_rows = [dict(zip(trade_columns, row)) for row in trade_conn.execute("SELECT * FROM index_trade WHERE TRY_CAST(Date AS DATE) >= DATE '2020-01-01'").fetchall()]
    finally:
        trade_conn.close()

    asian_currency = {"jpy", "cny", "rmb", "hkd", "inr", "krw", "twd", "sgd", "thb", "idr", "myr", "php", "vnd", "pkr", "bdt", "lkr"}
    asian_words = {"japan", "china", "hong kong", "india", "korea", "taiwan", "singapore", "thailand", "indonesia", "malaysia", "philippines", "vietnam", "pakistan", "bangladesh", "sri lanka", "asia"}
    info_by_symbol: dict[str, bool] = {}
    for row in info_rows:
        joined = " ".join(normalize_space(value).lower() for value in row.values())
        is_asia = any(word in joined for word in asian_words) or any(normalize_space(value).lower() in asian_currency for value in row.values())
        for key in ("Index", "index", "Symbol", "symbol", "Ticker", "ticker", "Exchange", "exchange"):
            if key in row and row[key] is not None:
                info_by_symbol[normalize_key(row[key])] = is_asia

    known_asia_symbols = {
        "n225", "nikkei225", "hsi", "hangseng", "ssec", "shanghai", "szse", "sse",
        "ks11", "kospi", "twii", "sti", "sensex", "bsesn", "nsei", "nifty50",
        "jkse", "klse", "set", "psei", "vni", "000001ss", "399001sz",
    }
    values: dict[str, list[float]] = defaultdict(list)
    display: dict[str, str] = {}
    for row in trade_rows:
        symbol = normalize_space(row.get("Index"))
        key = normalize_key(symbol)
        is_asia = info_by_symbol.get(key, False) or key in known_asia_symbols or any(token in key for token in known_asia_symbols)
        if not is_asia:
            continue
        try:
            opening = float(row.get("Open"))
            high = float(row.get("High"))
            low = float(row.get("Low"))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(item) for item in (opening, high, low)) or opening == 0:
            continue
        values[key].append((high - low) / abs(opening))
        display[key] = symbol
    if not values:
        raise RuntimeError("No Asian index rows were identified")
    averages = {key: sum(series) / len(series) for key, series in values.items() if series}
    winner = max(averages, key=lambda key: (averages[key], display[key]))
    return {"index": display[winner], "average_intraday_volatility": averages[winner]}


def solve_usaspending(paths: Paths) -> int:
    root = paths.dab_root / "query_usaspending" / "query_dataset"
    contract_rows = pg_rows("usaspending_contracts", "SELECT award_id, awarding_agency FROM contracts")
    amount_rows = pg_rows("usaspending_contracts", "SELECT award_id, amount_text FROM contract_amounts")
    alias_rows = duck_rows(root / "agencies.duckdb", "SELECT surface_form, canonical_name FROM agency_aliases")
    defense_aliases = {
        normalize_key(surface)
        for surface, canonical in alias_rows
        if normalize_key(canonical) == "departmentofdefense"
    }
    defense_aliases.update({"departmentofdefense", "dod", "deptofdefense", "defensedepartment"})

    # Every surviving primary amount row is one award entity.  Signatures map to
    # that entity, not merely to a numeric value, so multiple contract-side
    # surface forms of the same award cannot be double-counted.
    amount_index: dict[str, tuple[int, float]] = {}
    collisions: set[str] = set()
    for entity_id, (award_id, amount_text) in enumerate(amount_rows):
        if is_superseded_identifier(award_id):
            continue
        amount = parse_money(amount_text)
        if amount is None or not math.isfinite(amount):
            continue
        payload = (entity_id, float(amount))
        for signature in identifier_signatures(award_id):
            existing = amount_index.get(signature)
            if existing is not None and existing[0] != entity_id:
                collisions.add(signature)
            else:
                amount_index[signature] = payload
    for signature in collisions:
        amount_index.pop(signature, None)

    qualifying: set[int] = set()
    for award_id, agency in contract_rows:
        if normalize_key(agency) not in defense_aliases:
            continue
        signatures = identifier_signatures(award_id)
        exact_payloads = {
            amount_index[signature]
            for signature in signatures
            if signature in amount_index
        }
        payload: tuple[int, float] | None
        if len(exact_payloads) == 1:
            payload = next(iter(exact_payloads))
        elif len(exact_payloads) > 1:
            # Ambiguous exact resolution is safer to skip than to invent a join.
            payload = None
        else:
            fuzzy = fuzzy_signature_match(signatures, amount_index, threshold=0.94)
            payload = fuzzy if isinstance(fuzzy, tuple) and len(fuzzy) == 2 else None
        if payload is not None:
            entity_id, amount = payload
            if amount > 1_000_000:
                qualifying.add(entity_id)
    return len(qualifying)

def extract_publication_year(details: Any) -> int | None:
    text = normalize_space(details)
    if not text:
        return None
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        parsed = None
    candidates: list[str] = []
    if isinstance(parsed, Mapping):
        prioritized = []
        fallback = []
        for key, value in parsed.items():
            key_text = normalize_space(key).lower()
            target = prioritized if any(token in key_text for token in ("publication", "published", "release", "date")) else fallback
            target.append(normalize_space(value))
        candidates.extend(prioritized + fallback)
    elif isinstance(parsed, (list, tuple)):
        candidates.extend(normalize_space(value) for value in parsed)
    candidates.append(text)
    for candidate in candidates:
        years = [int(value) for value in YEAR_RE.findall(candidate)]
        years = [year for year in years if 1800 <= year <= 2023]
        if years:
            return years[0]
    return None


def solve_bookreview(paths: Paths) -> dict[str, Any]:
    root = paths.dab_root / "query_bookreview" / "query_dataset"
    books = pg_rows("bookreview_db", "SELECT book_id, details FROM books_info")
    year_items: list[tuple[Any, tuple[str, int]]] = []
    for book_id, details in books:
        year = extract_publication_year(details)
        signatures = identifier_signatures(book_id, ("book", "bookid", "asin", "isbn"))
        if year is not None and signatures:
            year_items.append((book_id, (min(signatures, key=len), int(year))))
    years, _ = unique_signature_index(year_items, ("book", "bookid", "asin", "isbn"))
    review_rows = sqlite_rows(root / "review_query.db", "SELECT purchase_id, rating FROM review")
    ratings_by_decade: dict[int, list[float]] = defaultdict(list)
    books_by_decade: dict[int, set[str]] = defaultdict(set)
    for purchase_id, rating in review_rows:
        signatures = identifier_signatures(purchase_id, ("purchase", "purchaseid", "book", "bookid", "asin", "isbn"))
        exact = [(signature, years[signature]) for signature in signatures if signature in years]
        if exact:
            _matched_surface, payload = max(exact, key=lambda item: len(item[0]))
        else:
            payload = fuzzy_signature_match(signatures, years, threshold=0.9)
        if payload is None:
            continue
        matched_signature, year = payload
        try:
            score = float(rating)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        decade = int(year) - int(year) % 10
        ratings_by_decade[decade].append(score)
        books_by_decade[decade].add(matched_signature)
    eligible = {
        decade: sum(ratings_by_decade[decade]) / len(ratings_by_decade[decade])
        for decade in ratings_by_decade
        if len(books_by_decade[decade]) >= 10 and ratings_by_decade[decade]
    }
    if not eligible:
        raise RuntimeError("No decade has at least ten rated books")
    winner = max(eligible, key=lambda decade: (eligible[decade], decade))
    return {"decade": f"{winner}s", "average_rating": eligible[winner], "distinct_books": len(books_by_decade[winner])}

def solve_music(paths: Paths) -> float:
    root = paths.dab_root / "query_music_brainz_20k" / "query_dataset"
    all_tracks = sqlite_rows(root / "tracks.db", "SELECT track_id, title, artist, album, year FROM tracks")
    target_title = normalize_key("Get Me Bodied")
    target_artist = normalize_key("Beyoncé")
    track_ids: list[int] = []
    for track_id, title, artist, _album, _year in all_tracks:
        title_key = normalize_key(re.sub(r"\s*[\[(].*?[\])]\s*$", "", normalize_space(title)))
        artist_key = normalize_key(artist)
        artist_match = artist_key == target_artist or difflib.SequenceMatcher(None, artist_key, target_artist, autojunk=False).ratio() >= 0.92
        title_match = (
            title_key == target_title
            or target_title in title_key
            or difflib.SequenceMatcher(None, title_key, target_title, autojunk=False).ratio() >= 0.9
        )
        if artist_match and title_match:
            track_ids.append(int(track_id))
    if not track_ids:
        return 0.0
    conn = duckdb.connect(str(root / "sales.duckdb"), read_only=True)
    try:
        placeholders = ",".join("?" for _ in track_ids)
        query = (
            f"SELECT COALESCE(SUM(revenue_usd), 0) FROM sales WHERE track_id IN ({placeholders}) "
            "AND lower(trim(country)) = 'canada' AND lower(trim(store)) = 'apple music'"
        )
        value = conn.execute(query, track_ids).fetchone()[0]
        return float(value or 0.0)
    finally:
        conn.close()

def write_answer(output_dir: Path, query_id: str, answer: Any) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{query_id}.json").write_text(json.dumps(answer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if isinstance(answer, dict) and "projects" in answer:
        projects = answer["projects"]
        with (output_dir / f"{query_id}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["project_name"])
            writer.writerows([[project] for project in projects])
        plain = "\n".join(projects)
    elif isinstance(answer, dict) and "index" in answer:
        plain = str(answer["index"])
    elif isinstance(answer, dict) and "decade" in answer:
        plain = str(answer["decade"])
    elif isinstance(answer, float):
        plain = f"{answer:.10f}".rstrip("0").rstrip(".")
    else:
        plain = str(answer)
    (output_dir / f"{query_id}.txt").write_text(plain + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dab-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    paths = Paths(args.dab_root.resolve(), args.output_dir.resolve())
    answers: dict[str, Any] = {}
    solvers = {
        "civic_unstructured_1": solve_civic,
        "cve_1": solve_cve,
        "stockindex_1": solve_stockindex,
        "usaspending_1": solve_usaspending,
        "bookreview_1": solve_bookreview,
        "music_brainz_20k_1": solve_music,
    }
    for query_id, solver in solvers.items():
        answer = solver(paths)
        answers[query_id] = answer
        write_answer(paths.output_dir, query_id, answer)
        print(json.dumps({"query_id": query_id, "answer": answer}, sort_keys=True), flush=True)
    (paths.output_dir / "answers.json").write_text(json.dumps(answers, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
