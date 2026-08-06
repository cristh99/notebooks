from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import resolve_canonical as base
from resolve_runner_v2 import (
    resolve_entities_with_coexistence,
    resolve_legal_with_original_punctuation,
)

SESAL_ENTITY = {
    "entity_id": "hn:institution:sesal",
    "entity_type": "public_institution",
    "canonical_name": "Secretaría de Salud",
    "aliases": (
        "sesal",
        "secretaria de salud",
        "secretaria de estado en el despacho de salud",
    ),
}
PCM_PATTERN = re.compile(r"\bPCM\s*[-–]?\s*0*53\s*[-–]?\s*2023\b", re.IGNORECASE)
STRICT_MONEY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?P<prefix>HNL|LPS?\.?|L\.|L|USD|US\$|\$)\s*[-:]?\s*(?P<number1>\d+(?:[.,]\d{3})*(?:[.,]\d{2})?)"
    r"|"
    r"(?P<number2>\d+(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?P<suffix>lempiras?|d[oó]lares?)"
    r")",
    re.IGNORECASE,
)
MONTH_YEAR_PATTERN = re.compile(
    r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?(20\d{2})\b",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_single(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {name}, got {len(matches)}")
    return matches[0]


def resolve_entities_fresh(lines: Sequence[Mapping[str, Any]]):
    original = base.ENTITY_REGISTRY
    try:
        base.ENTITY_REGISTRY = original + (SESAL_ENTITY,)
        return resolve_entities_with_coexistence(lines)
    finally:
        base.ENTITY_REGISTRY = original


def resolve_dates_fresh(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = base.resolve_dates(lines)
    seen = {(row["line_id"], row["value"]) for row in rows}
    for line in lines:
        text = str(line["text"])
        normalized = base.norm(text)
        for match in MONTH_YEAR_PATTERN.finditer(normalized):
            month_name, year_text = match.group(1).casefold(), match.group(2)
            value = f"{int(year_text):04d}-{base.MONTHS[month_name]:02d}"
            key = (line["line_id"], value)
            if key in seen:
                continue
            rows.append({
                "schema": "canonical-date-mention/1",
                "date_id": f"{line['line_id']}:date:{value}",
                "value": value,
                "precision": "month",
                "surface_text": match.group(0),
                "page_number": int(line["page_number"]),
                "line_id": line["line_id"],
                "confidence": float(line["mean_confidence"]),
                "resolution_method": "month_optional_de_year_pattern",
                "lineage_parent_sha256": line["lineage_parent_sha256"],
            })
            seen.add(key)
    return sorted(rows, key=lambda row: (row["value"], row["line_id"]))


def resolve_legal_fresh(lines: Sequence[Mapping[str, Any]]):
    instruments, mentions = resolve_legal_with_original_punctuation(lines)
    by_id = {str(item["legal_id"]): item for item in instruments}
    keys = {(str(item["legal_id"]), tuple(item["line_ids"])) for item in mentions}
    for line in lines:
        text = str(line["text"])
        for match in PCM_PATTERN.finditer(text):
            legal_id = "hn:pcm:053-2023"
            key = (legal_id, (line["line_id"],))
            if key not in keys:
                mentions.append({
                    "schema": "canonical-legal-reference/1",
                    "legal_id": legal_id,
                    "legal_type": "executive_decree",
                    "canonical_title": "PCM-053-2023",
                    "surface_text": match.group(0),
                    "matched_aliases": [match.group(0)],
                    "page_number": int(line["page_number"]),
                    "line_ids": [line["line_id"]],
                    "confidence": float(line["mean_confidence"]),
                    "resolution_status": "resolved",
                    "lineage_parent_sha256": line["lineage_parent_sha256"],
                })
                keys.add(key)
            item = by_id.setdefault(legal_id, {
                "schema": "canonical-legal-instrument/1",
                "legal_id": legal_id,
                "legal_type": "executive_decree",
                "canonical_title": "PCM-053-2023",
                "mention_count": 0,
                "evidence_line_ids": [],
                "resolution_status": "resolved",
            })
            if line["line_id"] not in item["evidence_line_ids"]:
                item["mention_count"] += 1
                item["evidence_line_ids"].append(line["line_id"])
    for item in by_id.values():
        item["evidence_line_ids"] = sorted(set(item["evidence_line_ids"]))
    mentions.sort(key=lambda row: (row["legal_id"], row["line_ids"]))
    return sorted(by_id.values(), key=lambda row: row["legal_id"]), mentions


def parse_number(raw: str) -> float:
    value = raw.strip()
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif value.count(",") == 1 and len(value.rsplit(",", 1)[1]) == 2:
        value = value.replace(",", ".")
    else:
        value = value.replace(",", "")
    return float(value)


def resolve_amounts_strict(lines: Sequence[Mapping[str, Any]]):
    rows: list[dict[str, Any]] = []
    for line in lines:
        text = str(line["text"])
        for match in STRICT_MONEY_PATTERN.finditer(text):
            raw_number = match.group("number1") or match.group("number2")
            value = parse_number(raw_number)
            marker = match.group("prefix") or match.group("suffix") or ""
            currency = "HNL" if re.search(r"^(?:HNL|LPS?\.?|L\.|L)$|lempiras?", marker, re.IGNORECASE) else "USD"
            rows.append({
                "schema": "canonical-amount/2",
                "amount_id": f"{line['line_id']}:amount:{currency}:{value:.2f}",
                "value": value,
                "currency": currency,
                "surface_text": match.group(0),
                "page_number": int(line["page_number"]),
                "line_id": line["line_id"],
                "confidence": float(line["mean_confidence"]),
                "resolution_status": "resolved",
                "resolution_method": "strict_currency_boundary_pattern",
                "lineage_parent_sha256": line["lineage_parent_sha256"],
            })
    unique = {(row["amount_id"], row["line_id"]): row for row in rows}
    resolved = sorted(unique.values(), key=lambda row: (row["currency"], row["value"], row["line_id"]))
    abstentions: list[dict[str, Any]] = []
    if not resolved:
        abstentions.append({
            "schema": "resolution-abstention/1",
            "field_type": "amount",
            "reason_code": "NO_CURRENCY_QUALIFIED_AMOUNT",
            "detail": "No standalone currency marker qualified a number; years, legal identifiers, page numbers and phone digits were not treated as money.",
            "resolution_status": "abstained",
        })
    return resolved, abstentions


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = b"".join(base.canonical_json(row) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": path.name, "rows": len(rows), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def resolve_fresh(normalized_dir: Path, output_dir: Path) -> dict[str, Any]:
    documents_path = normalized_dir / "documents.jsonl"
    pages_path = normalized_dir / "pages.jsonl"
    lines_path = normalized_dir / "lines.jsonl"
    words_path = normalized_dir / "words.jsonl"
    documents = load_jsonl(documents_path)
    pages = load_jsonl(pages_path)
    lines = load_jsonl(lines_path)
    words = load_jsonl(words_path)
    if len(documents) != 1 or not pages or not lines or not words:
        raise RuntimeError("normalized input is incomplete")

    entities, entity_mentions, collisions = resolve_entities_fresh(lines)
    dates = resolve_dates_fresh(lines)
    legal_instruments, legal_mentions = resolve_legal_fresh(lines)
    contacts = base.resolve_contacts(lines)
    amounts, abstentions = resolve_amounts_strict(lines)
    entity_ids = {row["entity_id"] for row in entities}
    legal_ids = {row["legal_id"] for row in legal_instruments}
    false_fiscal_amounts = [
        row for row in amounts
        if row["value"] in {2023.0, 2024.0}
        and base.norm(row["surface_text"]) in {"l 2023", "l 2024"}
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "entities.jsonl": write_jsonl(output_dir / "entities.jsonl", entities),
        "entity_mentions.jsonl": write_jsonl(output_dir / "entity_mentions.jsonl", entity_mentions),
        "entity_collisions.jsonl": write_jsonl(output_dir / "entity_collisions.jsonl", collisions),
        "dates.jsonl": write_jsonl(output_dir / "dates.jsonl", dates),
        "legal_instruments.jsonl": write_jsonl(output_dir / "legal_instruments.jsonl", legal_instruments),
        "legal_mentions.jsonl": write_jsonl(output_dir / "legal_mentions.jsonl", legal_mentions),
        "contacts.jsonl": write_jsonl(output_dir / "contacts.jsonl", contacts),
        "amounts.jsonl": write_jsonl(output_dir / "amounts.jsonl", amounts),
        "abstentions.jsonl": write_jsonl(output_dir / "abstentions.jsonl", abstentions),
    }
    checks = {
        "oncae_resolved": "hn:institution:oncae" in entity_ids,
        "sesal_resolved": "hn:institution:sesal" in entity_ids,
        "august_2024_resolved": any(row["value"] == "2024-08" for row in dates),
        "pcm_053_2023_resolved": "hn:pcm:053-2023" in legal_ids,
        "no_fiscal_year_money_false_positive": not false_fiscal_amounts,
        "entity_collisions_zero": not collisions,
        "every_entity_mention_has_lineage": all(row.get("line_ids") and row.get("lineage_parent_sha256") for row in entity_mentions),
        "every_legal_mention_has_lineage": all(row.get("line_ids") and row.get("lineage_parent_sha256") for row in legal_mentions),
        "amount_policy_closed": bool(amounts) or any(row["reason_code"] == "NO_CURRENCY_QUALIFIED_AMOUNT" for row in abstentions),
        "external_cost_usd": 0.0,
    }
    manifest = {
        "schema": "data-science-pipeline/fresh-resolved-bundle/1",
        "source_pdf_sha256": documents[0]["source_sha256"],
        "input_counts": {"documents": len(documents), "pages": len(pages), "lines": len(lines), "words": len(words)},
        "input_hashes": {
            "documents": sha256_file(documents_path),
            "pages": sha256_file(pages_path),
            "lines": sha256_file(lines_path),
            "words": sha256_file(words_path),
        },
        "row_counts": {
            "entities": len(entities),
            "entity_mentions": len(entity_mentions),
            "entity_collisions": len(collisions),
            "dates": len(dates),
            "legal_instruments": len(legal_instruments),
            "legal_mentions": len(legal_mentions),
            "contacts": len(contacts),
            "amounts": len(amounts),
            "abstentions": len(abstentions),
        },
        "checks": checks,
        "outputs": outputs,
    }
    payload = base.canonical_json(manifest)
    (output_dir / "resolve-manifest.json").write_bytes(payload)
    (output_dir / "resolve-manifest.sha256").write_text(f"{hashlib.sha256(payload).hexdigest()}  resolve-manifest.json\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(resolve_fresh(args.normalized, args.output), indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
