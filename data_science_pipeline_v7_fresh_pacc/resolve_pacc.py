from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import resolve_canonical as base
from resolve_runner_v2 import resolve_entities_with_coexistence
from resolve_fresh import resolve_amounts_strict

PACC_CONCEPT = {
    "entity_id": "hn:concept:pacc",
    "entity_type": "procurement_plan_concept",
    "canonical_name": "Plan Anual de Compras y Contrataciones",
    "aliases": (
        "pacc",
        "plan anual de compras y contrataciones",
        "planes anuales de compras y contrataciones",
        "plan anual de compras",
    ),
}
YEAR_PATTERN = re.compile(r"(?<![0-9-])\b(20\d{2})\b(?!-[0-9])")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = b"".join(base.canonical_json(dict(row)) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": path.name, "rows": len(rows), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def resolve_entities_pacc(lines: Sequence[Mapping[str, Any]]):
    original = base.ENTITY_REGISTRY
    try:
        base.ENTITY_REGISTRY = original + (PACC_CONCEPT,)
        return resolve_entities_with_coexistence(lines)
    finally:
        base.ENTITY_REGISTRY = original


def resolve_years(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = base.resolve_dates(lines)
    seen = {(row["line_id"], row["value"]) for row in rows}
    for line in lines:
        text = str(line["text"])
        for match in YEAR_PATTERN.finditer(text):
            year = match.group(1)
            key = (str(line["line_id"]), year)
            if key in seen:
                continue
            rows.append({
                "schema": "canonical-date-mention/1",
                "date_id": f"{line['line_id']}:date:{year}",
                "value": year,
                "precision": "year",
                "surface_text": match.group(0),
                "page_number": int(line["page_number"]),
                "line_id": line["line_id"],
                "confidence": float(line["mean_confidence"]),
                "resolution_method": "standalone_year_pattern",
                "lineage_parent_sha256": line["lineage_parent_sha256"],
            })
            seen.add(key)
    return sorted(rows, key=lambda row: (row["value"], row["line_id"]))


def resolve_pacc(normalized_dir: Path, output_dir: Path) -> dict[str, Any]:
    documents_path = normalized_dir / "documents.jsonl"
    pages_path = normalized_dir / "pages.jsonl"
    lines_path = normalized_dir / "lines.jsonl"
    words_path = normalized_dir / "words.jsonl"
    documents = load_jsonl(documents_path)
    pages = load_jsonl(pages_path)
    lines = load_jsonl(lines_path)
    words = load_jsonl(words_path)
    if len(documents) != 1 or len(pages) != 3 or not lines or not words:
        raise RuntimeError("normalized PACC input is incomplete")

    entities, entity_mentions, collisions = resolve_entities_pacc(lines)
    dates = resolve_years(lines)
    contacts = base.resolve_contacts(lines)
    amounts, abstentions = resolve_amounts_strict(lines)
    legal_instruments, legal_mentions = base.resolve_legal(lines)
    entity_ids = {row["entity_id"] for row in entities}
    false_year_amounts = [
        row for row in amounts
        if row["value"] in {2023.0, 2024.0}
        and row["surface_text"].strip().casefold() in {"l 2023", "l 2024"}
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
        "pacc_concept_resolved": "hn:concept:pacc" in entity_ids,
        "year_2023_resolved": any(row["value"] == "2023" and row["precision"] == "year" for row in dates),
        "no_fiscal_year_money_false_positive": not false_year_amounts,
        "entity_collisions_zero": not collisions,
        "entity_mention_lineage_complete": all(row.get("line_ids") and row.get("lineage_parent_sha256") for row in entity_mentions),
        "legal_mention_lineage_complete": all(row.get("line_ids") and row.get("lineage_parent_sha256") for row in legal_mentions),
        "amount_policy_closed": bool(amounts) or any(row["reason_code"] == "NO_CURRENCY_QUALIFIED_AMOUNT" for row in abstentions),
        "external_cost_usd": 0.0,
    }
    manifest = {
        "schema": "data-science-pipeline/fresh-pacc-resolved-bundle/1",
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
    print(json.dumps(resolve_pacc(args.normalized, args.output), indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
