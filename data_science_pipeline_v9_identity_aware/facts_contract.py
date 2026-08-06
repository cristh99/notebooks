from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

FACT_TYPES = ("circular_id", "date", "money", "email", "phone", "institution")


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_ascii(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fact_key(fact_type: str, value: str) -> str:
    if fact_type not in FACT_TYPES:
        raise ValueError(f"unsupported fact type: {fact_type}")
    return f"{fact_type}\u001f{value}"


def split_fact_key(key: str) -> tuple[str, str]:
    fact_type, separator, value = key.partition("\u001f")
    if not separator or fact_type not in FACT_TYPES or not value:
        raise ValueError(f"invalid fact key: {key!r}")
    return fact_type, value


def canonical_decimal(raw: str) -> str | None:
    compact = re.sub(r"\s+", "", raw)
    compact = re.sub(r"[^0-9.,]", "", compact)
    if not compact or not re.search(r"\d", compact):
        return None
    if compact.count(",") > 1 and "." not in compact:
        groups = compact.split(",")
        if not all(group.isdigit() for group in groups):
            return None
        if len(groups[-1]) == 2 and all(len(group) == 3 for group in groups[1:-1]):
            compact = "".join(groups[:-1]) + "." + groups[-1]
        elif all(len(group) == 3 for group in groups[1:]):
            compact = "".join(groups)
        else:
            return None
    elif compact.count(".") > 1 and "," not in compact:
        groups = compact.split(".")
        if not all(group.isdigit() for group in groups):
            return None
        if len(groups[-1]) == 2 and all(len(group) == 3 for group in groups[1:-1]):
            compact = "".join(groups[:-1]) + "." + groups[-1]
        elif all(len(group) == 3 for group in groups[1:]):
            compact = "".join(groups)
        else:
            return None
    elif "," in compact and "." in compact:
        last_comma = compact.rfind(",")
        last_dot = compact.rfind(".")
        decimal_index = max(last_comma, last_dot)
        fractional = compact[decimal_index + 1 :]
        if len(fractional) == 2:
            integral = re.sub(r"[.,]", "", compact[:decimal_index])
            if not integral.isdigit() or not fractional.isdigit():
                return None
            compact = integral + "." + fractional
        else:
            groups = re.split(r"[.,]", compact)
            if not all(group.isdigit() for group in groups) or not all(len(group) == 3 for group in groups[1:]):
                return None
            compact = "".join(groups)
    elif "," in compact or "." in compact:
        separator = "," if "," in compact else "."
        left, right = compact.split(separator, 1)
        if not left.isdigit() or not right.isdigit():
            return None
        if len(right) == 2:
            compact = left + "." + right
        elif len(right) == 3:
            compact = left + right
        else:
            return None
    elif not compact.isdigit():
        return None
    try:
        value = Decimal(compact)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0 or value > Decimal("1000000000000"):
        return None
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.quantize(Decimal("0.01")), "f")


def canonical_phone(country_digits: str, local_digits: str) -> str | None:
    country = re.sub(r"\D", "", country_digits)
    local = re.sub(r"\D", "", local_digits)
    if country not in {"", "504"} or len(local) != 8 or local[0] not in "234789":
        return None
    return "+504" + local


def sorted_fact_rows(keys: Iterable[str]) -> list[dict[str, str]]:
    rows = []
    for key in sorted(set(keys)):
        fact_type, value = split_fact_key(key)
        rows.append({"fact_type": fact_type, "value": value})
    return rows


def fact_set(payload: Mapping[str, Any]) -> set[str]:
    output: set[str] = set()
    for row in payload.get("facts", []):
        output.add(fact_key(str(row["fact_type"]), str(row["value"])))
    return output
