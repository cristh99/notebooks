"""Deterministic extraction of temporal project records and funding evidence."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date, datetime
import json
import re
import unicodedata
from typing import Iterable, Mapping, Sequence


_FIELD_ALIASES = {
    "project": "name",
    "project name": "name",
    "name": "name",
    "title": "name",
    "report date": "report_date",
    "report_date": "report_date",
    "date": "report_date",
    "as of": "report_date",
    "type": "project_type",
    "project type": "project_type",
    "category": "project_type",
    "status": "status",
    "project status": "status",
    "phase": "status",
    "amount": "amount",
    "funding": "amount",
    "funding amount": "amount",
    "grant amount": "amount",
}
_KEY_VALUE_RE = re.compile(r"^\s*[-*]?\s*([^:]{1,60})\s*:\s*(.*?)\s*$")
_MARKDOWN_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_DISASTER_SUFFIX_RE = re.compile(
    r"\s*\((?:FEMA|CALJPIA|CAL\s*OES|CALOES)\s+PROJECT\)\s*$",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")
_NON_NAME_RE = re.compile(r"[^A-Z0-9]+")


def _ascii(value: object) -> str:
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def canonical_project_name(value: object) -> str:
    """Canonicalize conservatively without erasing meaningful project identity."""
    text = _ascii(value).strip()
    text = _DISASTER_SUFFIX_RE.sub("", text)
    text = re.sub(r"^[#>*\-\s]+", "", text)
    text = _NON_NAME_RE.sub(" ", text.upper())
    return _SPACE_RE.sub(" ", text).strip()


def normalize_category(value: object) -> str:
    text = _SPACE_RE.sub(" ", _ascii(value).strip().lower())
    return text.replace("_", " ").replace("-", " ")


def parse_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _ascii(value).strip()
    if not text:
        return None
    iso_candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date()
    except ValueError:
        pass
    for pattern in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if match:
        return date(int(match.group(0)), 1, 1)
    return None


_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_SCALE_RE = re.compile(r"\b(K|THOUSAND|M|MM|MILLION|B|BILLION)\b", re.IGNORECASE)


def parse_amount(value: object) -> float | None:
    """Parse exact numeric/scaled amounts and explicit sums of numeric parts."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = _ascii(value).strip()
    if not text:
        return None

    # Split only explicit arithmetic operators. The word "and" is intentionally
    # not treated as addition because it is common inside English number prose.
    parts = re.split(r"\s*(?:\+|\bPLUS\b)\s*", text, flags=re.IGNORECASE)
    if len(parts) > 1:
        parsed = [parse_amount(part) for part in parts]
        return sum(parsed) if all(item is not None for item in parsed) else None

    match = _NUMBER_RE.search(text)
    if not match:
        return None
    number = float(match.group(0).replace(",", ""))
    scale_match = _SCALE_RE.search(text[match.end() :])
    if scale_match:
        token = scale_match.group(1).upper()
        if token in {"K", "THOUSAND"}:
            number *= 1_000
        elif token in {"M", "MM", "MILLION"}:
            number *= 1_000_000
        elif token in {"B", "BILLION"}:
            number *= 1_000_000_000
    return number


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    name: str
    report_date: date
    project_type: str
    status: str
    source: str = ""
    ordinal: int = 0

    @property
    def canonical_name(self) -> str:
        return canonical_project_name(self.name)


@dataclass(frozen=True, slots=True)
class FundingEntry:
    project_name: str
    funding_date: date
    amount: float
    source: str = ""

    @property
    def canonical_name(self) -> str:
        return canonical_project_name(self.project_name)


@dataclass(frozen=True, slots=True)
class SelectedProject:
    canonical_name: str
    display_name: str
    report_date: date
    project_type: str
    status: str
    accumulated_funding: float
    record_source: str
    funding_sources: tuple[str, ...]


def _canonical_field(value: object) -> str | None:
    text = normalize_category(value)
    return _FIELD_ALIASES.get(text)


def _record_from_mapping(
    mapping: Mapping[str, object], *, source: str, ordinal: int, fallback_name: str = ""
) -> ProjectRecord | None:
    normalized: dict[str, object] = {}
    for raw_key, value in mapping.items():
        key = _canonical_field(raw_key)
        if key:
            normalized[key] = value
    name = str(normalized.get("name") or fallback_name).strip()
    report_date = parse_date(normalized.get("report_date"))
    project_type = normalize_category(normalized.get("project_type"))
    status = normalize_category(normalized.get("status"))
    if not name or report_date is None or not project_type or not status:
        return None
    return ProjectRecord(name, report_date, project_type, status, source, ordinal)


def _funding_from_mapping(
    mapping: Mapping[str, object], *, source: str
) -> FundingEntry | None:
    normalized: dict[str, object] = {}
    for raw_key, value in mapping.items():
        key = _canonical_field(raw_key)
        if key:
            normalized[key] = value
    name = str(normalized.get("name") or "").strip()
    funding_date = parse_date(normalized.get("report_date"))
    amount = parse_amount(normalized.get("amount"))
    if not name or funding_date is None or amount is None:
        return None
    return FundingEntry(name, funding_date, amount, source)


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _extract_markdown_tables(text: str, *, source: str) -> list[ProjectRecord]:
    lines = text.splitlines()
    records: list[ProjectRecord] = []
    ordinal = 0
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or not _MARKDOWN_SEPARATOR_RE.match(lines[index + 1]):
            index += 1
            continue
        headers = _split_markdown_row(lines[index])
        mapped_headers = [_canonical_field(header) for header in headers]
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            cells = _split_markdown_row(lines[index])
            mapping = {
                header: cells[position]
                for position, header in enumerate(mapped_headers)
                if header and position < len(cells)
            }
            record = _record_from_mapping(mapping, source=source, ordinal=ordinal)
            if record:
                records.append(record)
                ordinal += 1
            index += 1
    return records


def _extract_literal_records(text: str, *, source: str) -> list[ProjectRecord]:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{(":
        return []
    value: object
    try:
        value = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        try:
            value = ast.literal_eval(stripped)
        except (ValueError, SyntaxError):
            return []
    if isinstance(value, Mapping):
        candidates: Sequence[object] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        candidates = value
    else:
        return []
    records: list[ProjectRecord] = []
    for ordinal, candidate in enumerate(candidates):
        if isinstance(candidate, Mapping):
            record = _record_from_mapping(candidate, source=source, ordinal=ordinal)
            if record:
                records.append(record)
    return records


def _extract_key_value_blocks(text: str, *, source: str) -> list[ProjectRecord]:
    lines = text.splitlines()
    records: list[ProjectRecord] = []
    current: dict[str, object] = {}
    heading = ""
    ordinal = 0

    def flush() -> None:
        nonlocal current, heading, ordinal
        record = _record_from_mapping(
            current, source=source, ordinal=ordinal, fallback_name=heading
        )
        if record:
            records.append(record)
            ordinal += 1
        current = {}
        heading = ""

    for raw_line in [*lines, ""]:
        line = raw_line.strip()
        if not line:
            if current:
                flush()
            continue
        match = _KEY_VALUE_RE.match(line)
        if match:
            field = _canonical_field(match.group(1))
            if field:
                # A repeated core field starts a new logical record even when
                # the source omitted a blank separator.
                if field in current and field in {"name", "report_date"}:
                    flush()
                current[field] = match.group(2).strip()
                continue
        if line.startswith("#"):
            if current:
                flush()
            heading = line.lstrip("#").strip()
        elif not current and len(line) <= 160:
            heading = line.strip("-*>").strip()
    return records


def extract_project_records(text: str, *, source: str = "") -> tuple[ProjectRecord, ...]:
    """Extract and stably deduplicate records from heterogeneous text layouts."""
    candidates = [
        *_extract_literal_records(text, source=source),
        *_extract_markdown_tables(text, source=source),
        *_extract_key_value_blocks(text, source=source),
    ]
    seen: set[tuple[str, date, str, str]] = set()
    output: list[ProjectRecord] = []
    for record in candidates:
        key = (
            record.canonical_name,
            record.report_date,
            normalize_category(record.project_type),
            normalize_category(record.status),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        output.append(record)
    return tuple(output)


def extract_funding_entries(text: str, *, source: str = "") -> tuple[FundingEntry, ...]:
    """Extract funding rows from Markdown tables, literals, or key-value blocks."""
    rows: list[Mapping[str, object]] = []
    stripped = text.strip()
    if stripped and stripped[0] in "[{(":
        try:
            literal = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            try:
                literal = ast.literal_eval(stripped)
            except (ValueError, SyntaxError):
                literal = None
        if isinstance(literal, Mapping):
            rows.append(literal)
        elif isinstance(literal, Sequence) and not isinstance(literal, (str, bytes, bytearray)):
            rows.extend(item for item in literal if isinstance(item, Mapping))

    lines = text.splitlines()
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or not _MARKDOWN_SEPARATOR_RE.match(lines[index + 1]):
            index += 1
            continue
        headers = _split_markdown_row(lines[index])
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            cells = _split_markdown_row(lines[index])
            rows.append(
                {
                    headers[position]: cells[position]
                    for position in range(min(len(headers), len(cells)))
                }
            )
            index += 1

    current: dict[str, object] = {}
    for raw_line in [*lines, ""]:
        line = raw_line.strip()
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        match = _KEY_VALUE_RE.match(line)
        if match and _canonical_field(match.group(1)):
            field = _canonical_field(match.group(1))
            if field in current and field in {"name", "report_date"}:
                rows.append(current)
                current = {}
            current[match.group(1)] = match.group(2)

    output: list[FundingEntry] = []
    seen: set[tuple[str, date, float, str]] = set()
    for mapping in rows:
        entry = _funding_from_mapping(mapping, source=source)
        if not entry:
            continue
        key = (entry.canonical_name, entry.funding_date, entry.amount, entry.source)
        if key not in seen:
            seen.add(key)
            output.append(entry)
    return tuple(output)


def latest_records_on_or_before(
    records: Iterable[ProjectRecord], cutoff: date
) -> dict[str, ProjectRecord]:
    latest: dict[str, ProjectRecord] = {}
    for record in records:
        canonical = record.canonical_name
        if not canonical or record.report_date > cutoff:
            continue
        incumbent = latest.get(canonical)
        if incumbent is None or (
            record.report_date,
            record.ordinal,
            record.source,
        ) > (
            incumbent.report_date,
            incumbent.ordinal,
            incumbent.source,
        ):
            latest[canonical] = record
    return latest


def aggregate_funding_on_or_before(
    entries: Iterable[FundingEntry], cutoff: date
) -> dict[str, tuple[float, tuple[str, ...]]]:
    totals: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    for entry in entries:
        canonical = entry.canonical_name
        if not canonical or entry.funding_date > cutoff:
            continue
        totals[canonical] = totals.get(canonical, 0.0) + float(entry.amount)
        if entry.source:
            sources.setdefault(canonical, set()).add(entry.source)
    return {
        canonical: (amount, tuple(sorted(sources.get(canonical, set()))))
        for canonical, amount in totals.items()
    }


def select_projects(
    records: Iterable[ProjectRecord],
    funding: Iterable[FundingEntry],
    *,
    cutoff: date,
    project_type: str,
    status: str,
    minimum_funding: float,
) -> tuple[SelectedProject, ...]:
    """Apply temporal semantics first, then filters and accumulated funding."""
    expected_type = normalize_category(project_type)
    expected_status = normalize_category(status)
    latest = latest_records_on_or_before(records, cutoff)
    totals = aggregate_funding_on_or_before(funding, cutoff)
    selected: list[SelectedProject] = []
    for canonical, record in latest.items():
        amount, funding_sources = totals.get(canonical, (0.0, ()))
        if normalize_category(record.project_type) != expected_type:
            continue
        if normalize_category(record.status) != expected_status:
            continue
        if amount <= minimum_funding:
            continue
        selected.append(
            SelectedProject(
                canonical_name=canonical,
                display_name=record.name,
                report_date=record.report_date,
                project_type=record.project_type,
                status=record.status,
                accumulated_funding=amount,
                record_source=record.source,
                funding_sources=funding_sources,
            )
        )
    return tuple(sorted(selected, key=lambda item: (item.canonical_name, item.display_name)))
