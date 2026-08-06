from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import resolve_canonical as base

_ORIGINAL_RESOLVE_LEGAL = base.resolve_legal
_DECREE_PATTERN = re.compile(
    r"\b(?:decretos?\s+legislativos?\s+)?(\d{1,4})\s*[-–]\s*(20\d{2})\b",
    re.IGNORECASE,
)


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
    base.resolve_legal = resolve_legal_with_original_punctuation
    print(json.dumps(base.resolve_bundle(args.bundle, args.output), indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
