from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from facts_contract import (
    canonical_decimal,
    canonical_json_bytes,
    canonical_phone,
    fact_key,
    normalize_ascii,
    normalize_space,
    sha256_file,
    split_fact_key,
)

MONTH_NUMBER = {
    "ENERO": "01",
    "FEBRERO": "02",
    "MARZO": "03",
    "ABRIL": "04",
    "MAYO": "05",
    "JUNIO": "06",
    "JULIO": "07",
    "AGOSTO": "08",
    "SEPTIEMBRE": "09",
    "SETIEMBRE": "09",
    "OCTUBRE": "10",
    "NOVIEMBRE": "11",
    "DICIEMBRE": "12",
}


def _date(day: str, month: str, year: str) -> str | None:
    try:
        day_number = int(day)
        month_number = int(month)
        year_number = int(year)
    except ValueError:
        return None
    limits = [31, 29 if year_number % 4 == 0 and (year_number % 100 != 0 or year_number % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not (2000 <= year_number <= 2099 and 1 <= month_number <= 12 and 1 <= day_number <= limits[month_number - 1]):
        return None
    return f"{year_number:04d}-{month_number:02d}-{day_number:02d}"


def _money(raw_currency: str, raw_number: str) -> str | None:
    value = canonical_decimal(raw_number)
    if value is None:
        return None
    if "." not in value and 1900 <= int(value) <= 2100:
        return None
    token = normalize_ascii(raw_currency).upper().replace(".", "")
    currency = "USD" if "USD" in token or "US$" in token or "DOLAR" in token else "HNL"
    return f"{currency}:{value}"


def extract_oracle_facts(native_text: str) -> dict[str, list[str]]:
    ascii_text = normalize_ascii(native_text)
    upper = ascii_text.upper()
    output: dict[str, list[str]] = {}

    circular_patterns = (
        re.compile(r"\bCIRCULAR\s+(?:N(?:O|RO|UMERO|[°º])\.?\s*)?(?:ONCAE\s*[-:]?\s*)?0*(\d{1,3})\s*[-/]\s*(20\d{2})\b", re.I),
        re.compile(r"\bONCAE\s*[-:]?\s*0*(\d{1,3})\s*[-/]\s*(20\d{2})\b", re.I),
    )
    for pattern in circular_patterns:
        for match in pattern.finditer(upper):
            key = fact_key("circular_id", f"ONCAE-{int(match.group(1)):03d}-{int(match.group(2)):04d}")
            output.setdefault(key, []).append(normalize_space(match.group(0)))

    month_names = "|".join(MONTH_NUMBER)
    for match in re.finditer(rf"\b([0-3]?\d)\s+DE\s+({month_names})\s+(?:DE|DEL)?\s*(20\d{{2}})\b", upper, re.I):
        value = _date(match.group(1), MONTH_NUMBER[match.group(2).upper()], match.group(3))
        if value:
            output.setdefault(fact_key("date", value), []).append(normalize_space(match.group(0)))
    for match in re.finditer(r"(?<!\d)([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})(?!\d)", upper):
        value = _date(match.group(1), match.group(2), match.group(3))
        if value:
            output.setdefault(fact_key("date", value), []).append(normalize_space(match.group(0)))

    money_patterns = (
        re.compile(r"(?<![A-Z0-9])(HNL|L\.?|LEMPIRAS?|USD|US\$)\s*(\d[\d., ]{0,24})", re.I),
        re.compile(r"(?<!\d)(\d[\d., ]{0,24})\s*(LEMPIRAS?|HNL|DOLARES?|USD)(?![A-Z])", re.I),
    )
    for index, pattern in enumerate(money_patterns):
        for match in pattern.finditer(upper):
            currency, number = (match.group(1), match.group(2)) if index == 0 else (match.group(2), match.group(1))
            value = _money(currency, number)
            if value:
                output.setdefault(fact_key("money", value), []).append(normalize_space(match.group(0)))

    for match in re.finditer(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", native_text, re.I):
        output.setdefault(fact_key("email", match.group(0).casefold()), []).append(match.group(0))

    phone_patterns = (
        re.compile(r"(?<!\d)\+?\s*504[\s.\-]*(\d{4})[\s.\-]*(\d{4})(?!\d)"),
        re.compile(r"\b(?:TELEFONO|TEL|PBX|CELULAR)\s*[:.\-]?\s*(\d{4})[\s.\-]*(\d{4})(?!\d)", re.I),
    )
    for index, pattern in enumerate(phone_patterns):
        for match in pattern.finditer(upper):
            value = canonical_phone("504" if index == 0 else "", match.group(1) + match.group(2))
            if value:
                output.setdefault(fact_key("phone", value), []).append(normalize_space(match.group(0)))

    if re.search(r"\bONCAE\b", upper):
        output.setdefault(fact_key("institution", "hn:institution:oncae"), []).append("ONCAE")

    return {key: sorted(set(values)) for key, values in output.items()}


def build_oracle(native_text_path: Path, pdf_sha256: str, output: Path, minimum_characters: int = 80) -> dict[str, Any]:
    native_text = native_text_path.read_text(encoding="utf-8", errors="strict")
    non_whitespace = len(re.sub(r"\s+", "", native_text))
    if non_whitespace < minimum_characters:
        result: dict[str, Any] = {
            "schema": "data-science-pipeline/native-text-oracle/1",
            "verdict": "BLOCKED_NO_NATIVE_ORACLE",
            "source_pdf_sha256": pdf_sha256,
            "native_text_sha256": sha256_file(native_text_path),
            "non_whitespace_characters": non_whitespace,
            "minimum_characters": minimum_characters,
            "facts": [],
        }
    else:
        facts_map = extract_oracle_facts(native_text)
        facts = []
        for key in sorted(facts_map):
            fact_type, value = split_fact_key(key)
            facts.append({"fact_type": fact_type, "value": value, "evidence": facts_map[key][:5]})
        result = {
            "schema": "data-science-pipeline/native-text-oracle/1",
            "verdict": "ORACLE_SEALED",
            "source_pdf_sha256": pdf_sha256,
            "native_text_sha256": sha256_file(native_text_path),
            "non_whitespace_characters": non_whitespace,
            "minimum_characters": minimum_characters,
            "facts": facts,
        }
    output.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(result)
    path = output / "oracle-facts.json"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (output / "oracle-facts.sha256").write_text(f"{digest}  oracle-facts.json\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-text", type=Path, required=True)
    parser.add_argument("--pdf-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_oracle(args.native_text, args.pdf_sha256, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
