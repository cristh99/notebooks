from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import resolve_canonical as base

_ORIGINAL_RESOLVE_ENTITIES = base.resolve_entities
_ORIGINAL_RESOLVE_LEGAL = base.resolve_legal
_DECREE_PATTERN = re.compile(
    r"\b(?:decretos?\s+legislativos?\s+)?(\d{1,4})\s*[-–]\s*(20\d{2})\b",
    re.IGNORECASE,
)


def resolve_entities_with_coexistence(
    lines: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    entities, mentions, false_collisions = _ORIGINAL_RESOLVE_ENTITIES(lines)
    line_by_id = {str(line["line_id"]): line for line in lines}
    registry = {str(item["entity_id"]): item for item in base.ENTITY_REGISTRY}
    mention_keys = {(str(item["entity_id"]), tuple(item["line_ids"])) for item in mentions}
    for collision in false_collisions:
        evidence_lines = [line_by_id[line_id] for line_id in collision["line_ids"]]
        text = str(collision["text"])
        normalized = base.norm(text)
        for entity_id in collision["candidate_entity_ids"]:
            spec = registry[entity_id]
            aliases = [str(alias) for alias in spec["aliases"] if base.norm(str(alias)) in normalized]
            if not aliases:
                continue
            key = (entity_id, tuple(collision["line_ids"]))
            if key in mention_keys:
                continue
            mentions.append({
                "schema": "canonical-entity-mention/1",
                "mention_id": f"{entity_id}:{collision['line_ids'][0]}:{collision['line_ids'][-1]}",
                "entity_id": entity_id,
                "entity_type": spec["entity_type"],
                "canonical_name": spec["canonical_name"],
                "surface_text": text,
                "matched_aliases": sorted(set(aliases)),
                "page_number": int(evidence_lines[0]["page_number"]),
                "start_line_id": collision["line_ids"][0],
                "end_line_id": collision["line_ids"][-1],
                "line_ids": list(collision["line_ids"]),
                "confidence": base.weighted_confidence(evidence_lines),
                "resolution_method": "deterministic_alias_registry_coexisting_mentions",
                "lineage_parent_sha256": evidence_lines[0]["lineage_parent_sha256"],
            })
            mention_keys.add(key)
    mentions.sort(key=lambda row: (row["entity_id"], row["page_number"], row["start_line_id"], row["end_line_id"]))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mention in mentions:
        grouped[str(mention["entity_id"])].append(mention)
    rebuilt: list[dict[str, Any]] = []
    for entity_id in sorted(grouped):
        spec = registry[entity_id]
        evidence = grouped[entity_id]
        rebuilt.append({
            "schema": "canonical-entity/1",
            "entity_id": entity_id,
            "entity_type": spec["entity_type"],
            "canonical_name": spec["canonical_name"],
            "aliases": sorted(set(alias for mention in evidence for alias in mention["matched_aliases"])),
            "mention_count": len(evidence),
            "mean_confidence": sum(float(item["confidence"]) for item in evidence) / len(evidence),
            "evidence_mention_ids": [item["mention_id"] for item in evidence],
            "resolution_status": "resolved",
        })
    # Multiple distinct named entities in one line are coexistence, not ambiguity.
    return rebuilt, mentions, []


def resolve_legal_with_original_punctuation(
    lines: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    instruments, mentions = _ORIGINAL_RESOLVE_LEGAL(lines)
    instrument_by_id = {str(item["legal_id"]): item for item in instruments}
    mention_keys = {(str(item["legal_id"]), tuple(item["line_ids"])) for item in mentions}
    for line in lines:
        text = str(line["text"])
        for match in _DECREE_PATTERN.finditer(text):
            number, year = match.group(1), match.group(2)
            legal_id = f"hn:decree:{number}-{year}"
            key = (legal_id, (line["line_id"],))
            if key not in mention_keys:
                mentions.append({
                    "schema": "canonical-legal-reference/1",
                    "legal_id": legal_id,
                    "legal_type": "legislative_decree",
                    "canonical_title": f"Decreto Legislativo {number}-{year}",
                    "surface_text": match.group(0),
                    "matched_aliases": [match.group(0)],
                    "page_number": int(line["page_number"]),
                    "line_ids": [line["line_id"]],
                    "confidence": float(line["mean_confidence"]),
                    "resolution_status": "resolved",
                    "lineage_parent_sha256": line["lineage_parent_sha256"],
                })
                mention_keys.add(key)
            item = instrument_by_id.setdefault(legal_id, {
                "schema": "canonical-legal-instrument/1",
                "legal_id": legal_id,
                "legal_type": "legislative_decree",
                "canonical_title": f"Decreto Legislativo {number}-{year}",
                "mention_count": 0,
                "evidence_line_ids": [],
                "resolution_status": "resolved",
            })
            if line["line_id"] not in item["evidence_line_ids"]:
                item["mention_count"] += 1
                item["evidence_line_ids"].append(line["line_id"])
    for item in instrument_by_id.values():
        item["evidence_line_ids"] = sorted(set(item["evidence_line_ids"]))
    mentions.sort(key=lambda row: (row["legal_id"], row["line_ids"]))
    return sorted(instrument_by_id.values(), key=lambda row: row["legal_id"]), mentions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base.resolve_entities = resolve_entities_with_coexistence
    base.resolve_legal = resolve_legal_with_original_punctuation
    print(json.dumps(base.resolve_bundle(args.bundle, args.output), indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
