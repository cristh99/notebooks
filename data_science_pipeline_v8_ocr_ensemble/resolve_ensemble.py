from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import resolve_canonical as base
from resolve_fresh import resolve_amounts_strict
from resolve_pacc import resolve_entities_pacc, resolve_years

TRUSTED_SOURCE_HOST = "oncae.gob.hn"
SOURCE_ENTITY_ID = "hn:institution:oncae"
PACC_ENTITY_ID = "hn:concept:pacc"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = b"".join(base.canonical_json(dict(row)) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": path.name, "rows": len(rows), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def source_bound_oncae(text_entities: Sequence[Mapping[str, Any]], text_mentions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evidence_lines = sorted({
        str(line_id)
        for mention in text_mentions
        if mention.get("entity_id") == SOURCE_ENTITY_ID
        for line_id in mention.get("line_ids", [])
    })
    text_row = next((row for row in text_entities if row.get("entity_id") == SOURCE_ENTITY_ID), None)
    return {
        "schema": "canonical-entity/1",
        "entity_id": SOURCE_ENTITY_ID,
        "entity_type": "public_institution",
        "canonical_name": "Oficina Normativa de Contratación y Adquisiciones del Estado",
        "aliases": ["ONCAE", TRUSTED_SOURCE_HOST],
        "mention_count": 0 if text_row is None else int(text_row.get("mention_count", 0)),
        "evidence_line_ids": evidence_lines,
        "resolution_status": "source_bound",
        "resolution_method": "trusted_source_host_registry",
    }


def resolve(normalized_dir: Path, output_dir: Path, source_host: str) -> dict[str, Any]:
    if source_host != TRUSTED_SOURCE_HOST:
        raise RuntimeError(f"untrusted source host: {source_host}")
    documents_path = normalized_dir / "documents.jsonl"
    pages_path = normalized_dir / "pages.jsonl"
    lines_path = normalized_dir / "lines.jsonl"
    words_path = normalized_dir / "words.jsonl"
    documents = load_jsonl(documents_path)
    pages = load_jsonl(pages_path)
    lines = load_jsonl(lines_path)
    words = load_jsonl(words_path)
    if len(documents) != 1 or len(pages) != 3 or not lines or not words:
        raise RuntimeError("normalized ensemble input is incomplete")

    text_entities, entity_mentions, collisions = resolve_entities_pacc(lines)
    entities = [dict(row) for row in text_entities if row.get("entity_id") != SOURCE_ENTITY_ID]
    entities.append(source_bound_oncae(text_entities, entity_mentions))
    entities.sort(key=lambda row: str(row["entity_id"]))
    source_bindings = [{
        "schema": "canonical-source-entity-binding/1",
        "binding_id": f"host:{TRUSTED_SOURCE_HOST}:{SOURCE_ENTITY_ID}",
        "source_host": TRUSTED_SOURCE_HOST,
        "entity_id": SOURCE_ENTITY_ID,
        "source_pdf_sha256": documents[0]["source_sha256"],
        "resolution_status": "resolved",
        "resolution_method": "trusted_source_host_registry",
    }]
    dates = resolve_years(lines)
    contacts = base.resolve_contacts(lines)
    amounts, abstentions = resolve_amounts_strict(lines)
    legal_instruments, legal_mentions = base.resolve_legal(lines)
    entity_ids = {str(row["entity_id"]) for row in entities}
    text_entity_ids = {str(row["entity_id"]) for row in text_entities}
    false_year_amounts = [
        row for row in amounts
        if float(row["value"]) in {2023.0, 2024.0}
        and str(row["surface_text"]).strip().casefold() in {"l 2023", "l 2024"}
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "entities.jsonl": write_jsonl(output_dir / "entities.jsonl", entities),
        "entity_mentions.jsonl": write_jsonl(output_dir / "entity_mentions.jsonl", entity_mentions),
        "entity_collisions.jsonl": write_jsonl(output_dir / "entity_collisions.jsonl", collisions),
        "source_bindings.jsonl": write_jsonl(output_dir / "source_bindings.jsonl", source_bindings),
        "dates.jsonl": write_jsonl(output_dir / "dates.jsonl", dates),
        "legal_instruments.jsonl": write_jsonl(output_dir / "legal_instruments.jsonl", legal_instruments),
        "legal_mentions.jsonl": write_jsonl(output_dir / "legal_mentions.jsonl", legal_mentions),
        "contacts.jsonl": write_jsonl(output_dir / "contacts.jsonl", contacts),
        "amounts.jsonl": write_jsonl(output_dir / "amounts.jsonl", amounts),
        "abstentions.jsonl": write_jsonl(output_dir / "abstentions.jsonl", abstentions),
    }
    checks = {
        "oncae_source_bound": SOURCE_ENTITY_ID in entity_ids and source_bindings[0]["source_host"] == TRUSTED_SOURCE_HOST,
        "pacc_text_entity_resolved": PACC_ENTITY_ID in text_entity_ids,
        "year_2023_resolved": any(row["value"] == "2023" and row["precision"] == "year" for row in dates),
        "no_fiscal_year_money_false_positive": not false_year_amounts,
        "entity_collisions_zero": not collisions,
        "entity_mention_lineage_complete": all(row.get("line_ids") and row.get("lineage_parent_sha256") for row in entity_mentions),
        "legal_mention_lineage_complete": all(row.get("line_ids") and row.get("lineage_parent_sha256") for row in legal_mentions),
        "amount_policy_closed": bool(amounts) or any(row["reason_code"] == "NO_CURRENCY_QUALIFIED_AMOUNT" for row in abstentions),
        "external_cost_usd": 0.0,
    }
    manifest = {
        "schema": "data-science-pipeline/fresh-pacc-ensemble-resolved-bundle/1",
        "source_host": source_host,
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
            "source_bindings": len(source_bindings),
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
    (output_dir / "resolve-manifest.sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  resolve-manifest.json\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-host", required=True)
    args = parser.parse_args()
    result = resolve(args.normalized, args.output, args.source_host)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    boolean_checks = {key: value for key, value in result["checks"].items() if key != "external_cost_usd"}
    if not all(boolean_checks.values()) or result["checks"]["external_cost_usd"] != 0.0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
