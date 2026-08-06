from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Sequence

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}

class NumericClass(str, Enum):
    MONETARY_AMOUNT = "MONETARY_AMOUNT"
    CALENDAR_DATE = "CALENDAR_DATE"
    FISCAL_PERIOD = "FISCAL_PERIOD"
    LEGAL_INSTRUMENT_ID = "LEGAL_INSTRUMENT_ID"
    TELEPHONE_CONTACT = "TELEPHONE_CONTACT"
    PAGE_LIST_NUMBER = "PAGE_LIST_NUMBER"
    UNRESOLVED_NUMERIC = "UNRESOLVED_NUMERIC"

@dataclass(frozen=True)
class NumericCandidate:
    schema: str
    line_id: str
    page_number: int
    surface_text: str
    span_start: int
    span_end: int
    semantic_class: NumericClass
    normalized_value: str
    lineage_parent_sha256: str
    confidence: float
    currency: str | None = None
    precision: str | None = None
    role_hint: str | None = None
    reason_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["semantic_class"] = self.semantic_class.value
        return out

_PREFIX_AMOUNT = re.compile(
    r"(?<![A-Za-z0-9_])(?P<currency>HNL|USD|US\$|\$|L(?:PS)?\.?)(?![A-Za-z0-9_])"
    r"\s*[-:]?\s*(?P<number>\d[\d.,]*)",
    re.IGNORECASE,
)
_SUFFIX_AMOUNT = re.compile(
    r"(?<![A-Za-z0-9_])(?P<number>\d[\d.,]*)\s*(?P<currency>lempiras?|d[oó]lares?)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(?<!\d)(?P<y>20\d{2})-(?P<m>0?[1-9]|1[0-2])-(?P<d>0?[1-9]|[12]\d|3[01])(?!\d)")
_DMY_DATE = re.compile(r"(?<!\d)(?P<d>0?[1-9]|[12]\d|3[01])(?P<sep>[/-])(?P<m>0?[1-9]|1[0-2])(?P=sep)(?P<y>20\d{2})(?!\d)")
_MONTH_YEAR = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b", re.IGNORECASE)
_LEGAL_ID = re.compile(r"(?<!\d)(?P<n>\d{1,4})\s*[-–]\s*(?P<y>20\d{2})(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+?504[\s.-]*)?(?:\d[\s.-]*){8}(?!\d)")
_FISCAL = re.compile(r"\b(?:ejercicio|a[nñ]o|periodo)\s+fiscal\s+(20\d{2})\b", re.IGNORECASE)
_PAGE_CONTEXT = re.compile(r"\b(?:p[aá]g(?:ina)?|page|folio|no\.?|n[úu]m(?:ero)?)\s*[:#.-]?\s*(\d{1,4})\b", re.IGNORECASE)

_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("payment_order", re.compile(r"\borden\s+de\s+pago\b", re.IGNORECASE)),
    ("payment", re.compile(r"\b(?:pago|pagado|pagada|desembolso)\b", re.IGNORECASE)),
    ("accrual", re.compile(r"\bdevengad[oa]\b", re.IGNORECASE)),
    ("commitment", re.compile(r"\b(?:compromiso|obligaci[oó]n)\b", re.IGNORECASE)),
    ("reception", re.compile(r"\b(?:recepci[oó]n|aceptaci[oó]n)\b", re.IGNORECASE)),
    ("liquidation", re.compile(r"\bliquidaci[oó]n\b", re.IGNORECASE)),
    ("contract", re.compile(r"\b(?:contrato|suscripci[oó]n)\b", re.IGNORECASE)),
    ("validity", re.compile(r"\bvigencia\b", re.IGNORECASE)),
)

def _explicit_role_hint(text: str, span_start: int, suffix: str) -> str | None:
    window = text[max(0, span_start - 80):span_start]
    hits: list[tuple[int, str]] = []
    for label, pattern in _ROLE_PATTERNS:
        for match in pattern.finditer(window):
            hits.append((match.end(), label))
    if not hits:
        return None
    _, label = max(hits)
    return f"{label}_{suffix}"

_LEGAL_CONTEXT = re.compile(r"\b(?:decreto|acuerdo|resoluci[oó]n|ley|reglamento|pcm)\b", re.IGNORECASE)

def _decimal(raw: str) -> Decimal:
    value = raw.strip()
    if "," in value and "." in value:
        if value.rfind(".") > value.rfind(","):
            value = value.replace(",", "")
        else:
            value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        tail = value.rsplit(",", 1)[1]
        value = value.replace(",", ".") if len(tail) in (1, 2) else value.replace(",", "")
    elif "." in value:
        tail = value.rsplit(".", 1)[1]
        if len(tail) not in (1, 2):
            value = value.replace(".", "")
    return Decimal(value)

def _currency(marker: str) -> str:
    normalized = unicodedata.normalize("NFKD", marker.casefold()).encode("ascii", "ignore").decode().replace(".", "")
    return "USD" if normalized in {"usd", "us$", "$", "dolar", "dolares"} else "HNL"

def _valid_ymd(y: int, m: int, d: int) -> bool:
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False

def _make(line: Mapping[str, Any], match: re.Match[str], semantic_class: NumericClass,
          normalized_value: str, *, currency: str | None = None,
          precision: str | None = None, role_hint: str | None = None,
          reason_code: str) -> NumericCandidate:
    return NumericCandidate(
        schema="data-science-pipeline/numeric-candidate/1",
        line_id=str(line["line_id"]),
        page_number=int(line["page_number"]),
        surface_text=match.group(0),
        span_start=match.start(),
        span_end=match.end(),
        semantic_class=semantic_class,
        normalized_value=normalized_value,
        lineage_parent_sha256=str(line["lineage_parent_sha256"]),
        confidence=float(line["mean_confidence"]),
        currency=currency,
        precision=precision,
        role_hint=role_hint,
        reason_code=reason_code,
    )

def classify_line(line: Mapping[str, Any]) -> list[NumericCandidate]:
    text = str(line["text"])
    candidates: list[NumericCandidate] = []
    occupied: list[tuple[int, int]] = []

    def overlaps(match: re.Match[str]) -> bool:
        return any(not (match.end() <= a or match.start() >= b) for a, b in occupied)

    def add(candidate: NumericCandidate) -> None:
        occupied.append((candidate.span_start, candidate.span_end))
        candidates.append(candidate)

    # Highest-specificity classes first. Date precedes telephone so hyphenated dates never become phones.
    for match in _FISCAL.finditer(text):
        year = match.group(1)
        add(_make(line, match, NumericClass.FISCAL_PERIOD, year, precision="year",
                  role_hint="fiscal_period", reason_code="EXPLICIT_FISCAL_CONTEXT"))

    for pattern, order in ((_ISO_DATE, "ymd"), (_DMY_DATE, "dmy")):
        for match in pattern.finditer(text):
            if overlaps(match):
                continue
            if order == "ymd":
                y, m, d = int(match.group("y")), int(match.group("m")), int(match.group("d"))
            else:
                y, m, d = int(match.group("y")), int(match.group("m")), int(match.group("d"))
            if _valid_ymd(y, m, d):
                add(_make(line, match, NumericClass.CALENDAR_DATE, f"{y:04d}-{m:02d}-{d:02d}",
                          precision="day", role_hint=_explicit_role_hint(text, match.start(), "date") or "document_body_date",
                          reason_code="EXPLICIT_FULL_DATE"))

    for match in _MONTH_YEAR.finditer(text):
        if overlaps(match):
            continue
        month = MONTHS[match.group(1).casefold()]
        year = int(match.group(2))
        add(_make(line, match, NumericClass.CALENDAR_DATE, f"{year:04d}-{month:02d}",
                  precision="month", role_hint=_explicit_role_hint(text, match.start(), "date") or "document_body_date",
                  reason_code="EXPLICIT_MONTH_YEAR"))

    for match in _LEGAL_ID.finditer(text):
        if overlaps(match):
            continue
        local_start = max(0, match.start() - 40)
        local_end = min(len(text), match.end() + 10)
        if _LEGAL_CONTEXT.search(text[local_start:local_end]):
            add(_make(line, match, NumericClass.LEGAL_INSTRUMENT_ID,
                      f"{match.group('n')}-{match.group('y')}",
                      role_hint="legal_reference", reason_code="LEGAL_CONTEXT_BOUND_ID"))

    for pattern in (_PREFIX_AMOUNT, _SUFFIX_AMOUNT):
        for match in pattern.finditer(text):
            if overlaps(match):
                continue
            try:
                value = _decimal(match.group("number"))
            except InvalidOperation:
                continue
            currency = _currency(match.group("currency"))
            add(_make(line, match, NumericClass.MONETARY_AMOUNT, format(value, "f"),
                      currency=currency, precision="exact_decimal",
                      role_hint=_explicit_role_hint(text, match.start(), "amount") or "amount_unspecified", reason_code="EXPLICIT_CURRENCY"))

    for match in _PHONE.finditer(text):
        if overlaps(match):
            continue
        digits = re.sub(r"\D", "", match.group(0))
        has_phone_context = bool(re.search(r"\b(?:tel(?:[ée]fono)?|cel(?:ular)?|contacto)\b",
                                           text[max(0, match.start()-20):match.start()],
                                           re.IGNORECASE))
        has_country_code = digits.startswith("504") and len(digits) == 11
        if has_country_code or has_phone_context:
            normalized = "+" + digits if has_country_code else digits
            add(_make(line, match, NumericClass.TELEPHONE_CONTACT, normalized,
                      role_hint="contact", reason_code="PHONE_FORM_OR_CONTEXT"))

    for match in _PAGE_CONTEXT.finditer(text):
        # Classify only the numeric subgroup span, not the whole phrase.
        start, end = match.span(1)
        proxy = _SpanProxy(text[start:end], start, end)
        if any(not (end <= a or start >= b) for a, b in occupied):
            continue
        add(_make(line, proxy, NumericClass.PAGE_LIST_NUMBER, match.group(1),
                  role_hint="page_or_list", reason_code="PAGE_CONTEXT"))

    # Keep unresolved numeric tokens explicit instead of coercing them.
    for match in re.finditer(r"(?<![A-Za-z0-9_])\d[\d./-]*\d|(?<![A-Za-z0-9_])\d(?![A-Za-z0-9_])", text):
        if overlaps(match):
            continue
        add(_make(line, match, NumericClass.UNRESOLVED_NUMERIC, match.group(0),
                  role_hint=None, reason_code="NUMERIC_TOKEN_AMBIGUOUS"))

    return sorted(candidates, key=lambda c: (c.span_start, c.span_end, c.semantic_class.value))

class _SpanProxy:
    """Minimal match-like object for a captured subgroup span."""
    def __init__(self, value: str, start: int, end: int) -> None:
        self._value, self._start, self._end = value, start, end
    def group(self, _index: int | str = 0) -> str:
        return self._value
    def start(self) -> int:
        return self._start
    def end(self) -> int:
        return self._end

def classify_lines(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [candidate.to_dict() for line in lines for candidate in classify_line(line)]
    return sorted(rows, key=lambda row: (row["page_number"], row["line_id"], row["span_start"], row["semantic_class"]))
