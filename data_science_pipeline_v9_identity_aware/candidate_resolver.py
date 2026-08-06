from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
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

EXPECTED_CANDIDATES = ("auto_300_psm3", "balanced_200_psm6", "sparse_300_psm11")
MONTHS = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}

CIRCULAR_RE = re.compile(
    r"\b(?:CIRCULAR\s+(?:N(?:O|RO|UMERO|[°º])\.?\s*)?)?ONCAE\s*[-–—:]?\s*0*(\d{1,3})\s*[-/]\s*(20\d{2})\b",
    re.IGNORECASE,
)
SPANISH_DATE_RE = re.compile(
    r"\b([0-3]?\d)\s+DE\s+(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|SETIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)\s+(?:DE|DEL)?\s*(20\d{2})\b",
    re.IGNORECASE,
)
NUMERIC_DATE_RE = re.compile(r"(?<!\d)([0-3]?\d)[/-]([01]?\d)[/-](20\d{2})(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_COUNTRY_RE = re.compile(r"(?<!\d)(?:\+?\s*504)[\s.\-]*(\d{4})[\s.\-]*(\d{4})(?!\d)")
PHONE_LABEL_RE = re.compile(
    r"\b(?:TEL(?:EFONO)?|PBX|CEL(?:ULAR)?)\s*[:.\-]?\s*(\d{4})[\s.\-]*(\d{4})(?!\d)",
    re.IGNORECASE,
)
MONEY_PREFIX_RE = re.compile(
    r"(?<![A-Z0-9])(?P<currency>HNL|L(?:EMPIRAS?)?\.?|USD|US\$)\s*(?P<number>\d[\d., ]{0,24})",
    re.IGNORECASE,
)
MONEY_SUFFIX_RE = re.compile(
    r"(?<!\d)(?P<number>\d[\d., ]{0,24})\s*(?P<currency>LEMPIRAS?|HNL|DOLARES?|USD)(?![A-Z])",
    re.IGNORECASE,
)


def _valid_date(day: int, month: int, year: int) -> str | None:
    if year < 2000 or year > 2099 or month < 1 or month > 12 or day < 1:
        return None
    month_days = (31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if day > month_days[month - 1]:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _money_currency(raw: str) -> str:
    token = normalize_ascii(raw).upper().replace(".", "")
    return "USD" if token in {"USD", "US$", "DOLAR", "DOLARES"} else "HNL"


def _year_like_integer(value: str) -> bool:
    if "." in value:
        return False
    try:
        integer = int(value)
    except ValueError:
        return False
    return 1900 <= integer <= 2100


def extract_facts(text: str) -> dict[str, list[str]]:
    normalized = normalize_ascii(text).upper()
    evidence: dict[str, list[str]] = defaultdict(list)

    for match in CIRCULAR_RE.finditer(normalized):
        number = int(match.group(1))
        year = int(match.group(2))
        evidence[fact_key("circular_id", f"ONCAE-{number:03d}-{year:04d}")].append(normalize_space(match.group(0)))

    for match in SPANISH_DATE_RE.finditer(normalized):
        value = _valid_date(int(match.group(1)), MONTHS[match.group(2).upper()], int(match.group(3)))
        if value:
            evidence[fact_key("date", value)].append(normalize_space(match.group(0)))
    for match in NUMERIC_DATE_RE.finditer(normalized):
        value = _valid_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if value:
            evidence[fact_key("date", value)].append(normalize_space(match.group(0)))

    for regex in (MONEY_PREFIX_RE, MONEY_SUFFIX_RE):
        for match in regex.finditer(normalized):
            value = canonical_decimal(match.group("number"))
            if value is None or _year_like_integer(value):
                continue
            currency = _money_currency(match.group("currency"))
            evidence[fact_key("money", f"{currency}:{value}")].append(normalize_space(match.group(0)))

    for match in EMAIL_RE.finditer(text):
        value = match.group(0).casefold()
        evidence[fact_key("email", value)].append(match.group(0))

    for match in PHONE_COUNTRY_RE.finditer(normalized):
        value = canonical_phone("504", match.group(1) + match.group(2))
        if value:
            evidence[fact_key("phone", value)].append(normalize_space(match.group(0)))
    for match in PHONE_LABEL_RE.finditer(normalized):
        value = canonical_phone("", match.group(1) + match.group(2))
        if value:
            evidence[fact_key("phone", value)].append(normalize_space(match.group(0)))

    if re.search(r"\bONCAE\b", normalized):
        evidence[fact_key("institution", "hn:institution:oncae")].append("ONCAE")

    return {key: sorted(set(values)) for key, values in evidence.items()}


def _load_candidate_text(candidate_root: Path) -> tuple[str, list[dict[str, Any]]]:
    files = sorted(candidate_root.glob("page_*.txt"))
    if not files:
        raise RuntimeError(f"no OCR pages in {candidate_root}")
    rows: list[dict[str, Any]] = []
    parts: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="strict")
        if not text.strip():
            raise RuntimeError(f"empty OCR page: {path}")
        rows.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        parts.append(text)
    return "\n\f\n".join(parts), rows


def resolve(ocr_root: Path, output: Path, minimum_support: int = 2) -> dict[str, Any]:
    manifest_path = ocr_root / "ocr-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = tuple(candidate["name"] for candidate in manifest.get("candidates", []))
    if names != EXPECTED_CANDIDATES:
        raise RuntimeError(f"candidate order mismatch: {names!r}")
    if minimum_support != 2:
        raise ValueError("v9 minimum support is frozen at two")

    supports: dict[str, set[str]] = defaultdict(set)
    surfaces: dict[str, dict[str, list[str]]] = defaultdict(dict)
    archives: dict[str, list[dict[str, Any]]] = {}
    for name in EXPECTED_CANDIDATES:
        text, archive = _load_candidate_text(ocr_root / name)
        archives[name] = archive
        facts = extract_facts(text)
        for key, values in facts.items():
            supports[key].add(name)
            surfaces[key][name] = values[:5]

    accepted_keys = sorted(key for key, names_set in supports.items() if len(names_set) >= minimum_support)
    abstained_keys = sorted(key for key, names_set in supports.items() if len(names_set) < minimum_support)
    facts = []
    for key in accepted_keys:
        fact_type, value = split_fact_key(key)
        facts.append(
            {
                "fact_type": fact_type,
                "value": value,
                "support_count": len(supports[key]),
                "supporting_candidates": sorted(supports[key]),
                "evidence": {name: surfaces[key][name] for name in sorted(surfaces[key])},
            }
        )
    abstentions = []
    for key in abstained_keys:
        fact_type, value = split_fact_key(key)
        abstentions.append(
            {
                "fact_type": fact_type,
                "value": value,
                "reason": "single_strategy_only",
                "support_count": len(supports[key]),
                "supporting_candidates": sorted(supports[key]),
            }
        )

    result = {
        "schema": "data-science-pipeline/identity-aware-candidate/1",
        "verdict": "CANDIDATE_SEALED",
        "source_pdf_sha256": manifest["source_pdf_sha256"],
        "ocr_manifest_sha256": sha256_file(manifest_path),
        "candidate_names": list(EXPECTED_CANDIDATES),
        "minimum_support": minimum_support,
        "native_text_used": False,
        "facts": facts,
        "abstentions": abstentions,
        "checks": {
            "three_candidates": len(EXPECTED_CANDIDATES) == 3,
            "all_pages_nonempty": all(row["bytes"] > 0 for rows in archives.values() for row in rows),
            "candidate_archives_hashed": all(row["sha256"] for rows in archives.values() for row in rows),
            "native_text_forbidden": True,
        },
        "archive": archives,
    }
    payload = canonical_json_bytes(result)
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "candidate-facts.json"
    result_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (output / "candidate-facts.sha256").write_text(f"{digest}  candidate-facts.json\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = resolve(args.ocr_root, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
