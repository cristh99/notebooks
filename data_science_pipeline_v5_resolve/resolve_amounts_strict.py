from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


_PREFIX_AMOUNT = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<currency>HNL|USD|US\$|\$|L(?:PS)?\.?)"
    r"(?![A-Za-z0-9_])"
    r"\s*[-:]?\s*"
    r"(?P<number>\d[\d.,]*)",
    re.IGNORECASE,
)
_SUFFIX_AMOUNT = re.compile(
    r"(?<![A-Za-z0-9_])(?P<number>\d[\d.,]*)\s*"
    r"(?P<currency>lempiras?|d[oó]lares?)"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


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
    normalized = marker.casefold().replace(".", "")
    return "USD" if normalized in {"usd", "us$", "$", "dolar", "dolares", "dólar", "dólares"} else "HNL"


def resolve_amounts_strict(
    lines: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve money only when the currency marker is a standalone token.

    The left boundary is material: it prevents the final ``L`` in words such
    as ``FISCAL 2024`` from being interpreted as the lempira marker ``L``.
    """
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in lines:
        text = str(line["text"])
        for pattern in (_PREFIX_AMOUNT, _SUFFIX_AMOUNT):
            for match in pattern.finditer(text):
                try:
                    value = _decimal(match.group("number"))
                except InvalidOperation:
                    continue
                currency = _currency(match.group("currency"))
                key = (str(line["line_id"]), currency, format(value, "f"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "schema": "canonical-amount/1",
                    "amount_id": f"{line['line_id']}:amount:{currency}:{float(value):.2f}",
                    "value": float(value),
                    "currency": currency,
                    "surface_text": match.group(0),
                    "page_number": int(line["page_number"]),
                    "line_id": line["line_id"],
                    "confidence": float(line["mean_confidence"]),
                    "resolution_status": "resolved",
                    "lineage_parent_sha256": line["lineage_parent_sha256"],
                })
    abstentions: list[dict[str, Any]] = []
    if not rows:
        abstentions.append({
            "schema": "resolution-abstention/1",
            "field_type": "amount",
            "reason_code": "NO_CURRENCY_QUALIFIED_AMOUNT",
            "detail": "No number had a standalone explicit currency marker; years, page numbers, decree numbers and phone digits were not treated as money.",
            "resolution_status": "abstained",
        })
    return sorted(rows, key=lambda row: (row["currency"], row["value"], row["line_id"])), abstentions
