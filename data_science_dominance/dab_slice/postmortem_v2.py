from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import psycopg2
from bson import decode_all
from rapidfuzz import fuzz, process

GT_CIVIC = [
    "2022 Annual Street Maintenance",
    "Annual Street Maintenance",
    "Civic Center Water Treatment Facility Phase 2",
    "Marie Canyon Green Streets",
    "Michael Landon Center Roof Replacement Project",
    "PCH Median Improvements Project",
    "PCH Signal Synchronization System Improvements Project",
    "PCH at Trancas Canyon Road Right Turn Lane",
    "Permanent Skate Park",
    "Westward Beach Road Improvements Project",
    "Westward Beach Road Repair Project",
]


def load_candidate(path: Path):
    spec = importlib.util.spec_from_file_location("dab_candidate_postmortem", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def diagnose_civic(agent, dab_root: Path, evidence: Path) -> dict:
    civic_root = dab_root / "query_civic_unstructured/query_dataset"
    docs = decode_all((civic_root / "civic_docs_dump/civic_db/civic_docs.bson").read_bytes())
    decoded_docs = []
    parser_counts = []
    gt_hits: dict[str, list[dict]] = defaultdict(list)
    structural_lines = []
    for ordinal, doc in enumerate(docs):
        content = str(doc.get("report_content", ""))
        report_date, records = agent.parse_project_records(content, None)
        lines = content.splitlines()
        parser_counts.append(
            {
                "ordinal": ordinal,
                "report_id": str(doc.get("report_id", "")),
                "report_date": report_date.isoformat() if report_date else None,
                "record_count": len(records),
                "content_chars": len(content),
                "line_count": len(lines),
            }
        )
        for line_index, line in enumerate(lines):
            lower = line.casefold()
            if any(
                token in lower
                for token in (
                    "project",
                    "capital",
                    "design",
                    "status",
                    "phase",
                    "publication",
                    "report date",
                )
            ):
                structural_lines.append(
                    {
                        "ordinal": ordinal,
                        "report_id": str(doc.get("report_id", "")),
                        "line_index": line_index,
                        "line": line[:800],
                    }
                )
            for name in GT_CIVIC:
                if name.casefold() in lower:
                    lo = max(0, line_index - 4)
                    hi = min(len(lines), line_index + 5)
                    gt_hits[name].append(
                        {
                            "ordinal": ordinal,
                            "report_id": str(doc.get("report_id", "")),
                            "line_index": line_index,
                            "context": lines[lo:hi],
                        }
                    )
        decoded_docs.append(
            {
                "ordinal": ordinal,
                "keys": sorted(str(key) for key in doc),
                "report_id": str(doc.get("report_id", "")),
                "other_fields": {
                    str(key): str(value)
                    for key, value in doc.items()
                    if key != "report_content"
                },
                "report_content": content,
            }
        )

    funding_conn = sqlite3.connect(civic_root / "funding.db")
    try:
        funding_tables = [
            row[0]
            for row in funding_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        funding_schema = {
            table: [
                {"name": row[1], "type": row[2]}
                for row in funding_conn.execute(f'PRAGMA table_info("{table}")')
            ]
            for table in funding_tables
        }
        funding_rows = [
            tuple(row)
            for row in funding_conn.execute(
                'SELECT project_name, grant_time, amount FROM "Funding"'
            )
        ]
    finally:
        funding_conn.close()

    funding_by_name: dict[str, float] = defaultdict(float)
    for name, grant_time, amount in funding_rows:
        parsed = agent.parse_date(grant_time)
        if parsed and parsed <= agent.date(2023, 1, 1):
            funding_by_name[str(name)] += float(amount)

    report = {
        "schema": "data-science-dominance/dab-civic-postmortem/2",
        "document_count": len(docs),
        "document_key_frequencies": dict(
            Counter(str(key) for doc in docs for key in doc)
        ),
        "parser_counts": parser_counts,
        "parser_total_records": sum(row["record_count"] for row in parser_counts),
        "ground_truth_name_hits": dict(gt_hits),
        "ground_truth_hit_count": sum(bool(gt_hits.get(name)) for name in GT_CIVIC),
        "structural_lines": structural_lines[:1000],
        "funding_tables": funding_tables,
        "funding_schema": funding_schema,
        "funding_row_count": len(funding_rows),
        "funding_totals_for_ground_truth": {
            name: funding_by_name.get(name, 0.0) for name in GT_CIVIC
        },
        "candidate_output": agent.solve_civic(agent.Paths(dab_root, evidence)),
    }
    (evidence / "civic-postmortem.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (evidence / "civic-docs-decoded.json").write_text(
        json.dumps(decoded_docs, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return report


def diagnose_usaspending(agent, dab_root: Path, evidence: Path) -> dict:
    usa_root = dab_root / "query_usaspending/query_dataset"
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="postgres",
        dbname="usaspending_contracts",
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT award_id, awarding_agency FROM contracts")
            contracts = list(cursor.fetchall())
            cursor.execute("SELECT award_id, amount_text FROM contract_amounts")
            amounts = list(cursor.fetchall())
    finally:
        conn.close()

    alias_conn = duckdb.connect(str(usa_root / "agencies.duckdb"), read_only=True)
    try:
        aliases = alias_conn.execute(
            "SELECT surface_form, canonical_name FROM agency_aliases"
        ).fetchall()
    finally:
        alias_conn.close()
    defense_aliases = {
        agent.normalize_key(surface)
        for surface, canonical in aliases
        if agent.normalize_key(canonical) == "departmentofdefense"
    }
    defense_aliases.update(
        {"departmentofdefense", "dod", "deptofdefense", "defensedepartment"}
    )
    dod_contracts = [
        (award_id, agency)
        for award_id, agency in contracts
        if agent.normalize_key(agency) in defense_aliases
    ]

    def primary_signature(value) -> str:
        text = agent.normalize_space(value)
        text = re.sub(r"(?i)[\s_.-]*OLD$", "", text)
        body = agent._ID_PREFIX_RE.sub("", text, count=1)
        compact = re.sub(r"[^A-Za-z0-9]+", "", body)
        return compact.translate(agent._OCR_TO_DIGIT).lower()

    parse_stats = Counter()
    amount_entities = []
    amount_signature_entities: dict[str, set[int]] = defaultdict(set)
    primary_entities: dict[str, set[int]] = defaultdict(set)
    for entity_id, (award_id, amount_text) in enumerate(amounts):
        old = agent.is_superseded_identifier(award_id)
        parsed = agent.parse_money(amount_text)
        parse_stats["total"] += 1
        parse_stats["old"] += int(old)
        parse_stats["parsed"] += int(parsed is not None and math.isfinite(parsed))
        parse_stats["parsed_gt_1m_non_old"] += int(
            parsed is not None
            and math.isfinite(parsed)
            and parsed > 1_000_000
            and not old
        )
        if old or parsed is None or not math.isfinite(parsed):
            continue
        signatures = agent.identifier_signatures(award_id)
        primary = primary_signature(award_id)
        amount_entities.append(
            {
                "entity_id": entity_id,
                "award_id": str(award_id),
                "amount_text": str(amount_text),
                "parsed_amount": float(parsed),
                "signatures": sorted(signatures),
                "primary_signature": primary,
            }
        )
        for signature in signatures:
            amount_signature_entities[signature].add(entity_id)
        primary_entities[primary].add(entity_id)

    unique_signature_map = {
        signature: next(iter(ids))
        for signature, ids in amount_signature_entities.items()
        if len(ids) == 1
    }
    unique_primary_map = {
        signature: next(iter(ids))
        for signature, ids in primary_entities.items()
        if len(ids) == 1
    }
    entity_by_id = {row["entity_id"]: row for row in amount_entities}
    stage = Counter()
    unresolved = []
    exact_join_entities = set()
    primary_join_entities = set()
    exact_qualifying = set()
    for award_id, agency in dod_contracts:
        signatures = agent.identifier_signatures(award_id)
        payloads = {
            unique_signature_map[signature]
            for signature in signatures
            if signature in unique_signature_map
        }
        if len(payloads) == 1:
            stage["candidate_exact_unique"] += 1
            entity_id = next(iter(payloads))
            exact_join_entities.add(entity_id)
            if entity_by_id[entity_id]["parsed_amount"] > 1_000_000:
                exact_qualifying.add(entity_id)
        elif len(payloads) > 1:
            stage["candidate_exact_ambiguous"] += 1
        else:
            stage["candidate_no_exact"] += 1

        primary = primary_signature(award_id)
        primary_ids = primary_entities.get(primary, set())
        if len(primary_ids) == 1:
            stage["primary_exact_unique"] += 1
            primary_join_entities.update(primary_ids)
        elif len(primary_ids) > 1:
            stage["primary_exact_ambiguous"] += 1
        else:
            stage["primary_no_exact"] += 1
            unresolved.append(
                {
                    "contract_award_id": str(award_id),
                    "agency": str(agency),
                    "candidate_signatures": sorted(signatures),
                    "primary_signature": primary,
                }
            )

    primary_choices = list(unique_primary_map)
    score_bands = Counter()
    for row in unresolved[:500]:
        match = process.extractOne(
            row["primary_signature"], primary_choices, scorer=fuzz.ratio, score_cutoff=0
        )
        if match:
            key, score, _ = match
            row["best_primary_match"] = key
            row["best_primary_score"] = score
            row["best_amount_entity"] = entity_by_id[unique_primary_map[key]]
            floor = int(score // 5) * 5
            score_bands[f"{floor:02d}-{floor + 4:02d}"] += 1

    report = {
        "schema": "data-science-dominance/dab-usaspending-postmortem/2",
        "ground_truth_count": 898,
        "candidate_count": agent.solve_usaspending(agent.Paths(dab_root, evidence)),
        "contract_rows": len(contracts),
        "distinct_contract_surface_ids": len({str(row[0]) for row in contracts}),
        "agency_surface_counts": dict(Counter(str(agency) for _, agency in contracts)),
        "defense_aliases": sorted(defense_aliases),
        "dod_contract_rows": len(dod_contracts),
        "dod_distinct_contract_surface_ids": len(
            {str(row[0]) for row in dod_contracts}
        ),
        "amount_rows": len(amounts),
        "amount_parse_stats": dict(parse_stats),
        "surviving_amount_entities": len(amount_entities),
        "signature_count": len(amount_signature_entities),
        "signature_collision_count": sum(
            len(ids) > 1 for ids in amount_signature_entities.values()
        ),
        "primary_signature_count": len(primary_entities),
        "primary_collision_count": sum(
            len(ids) > 1 for ids in primary_entities.values()
        ),
        "join_stage_counts": dict(stage),
        "candidate_exact_join_distinct_entities": len(exact_join_entities),
        "primary_exact_join_distinct_entities": len(primary_join_entities),
        "candidate_qualifying_from_exact_only": len(exact_qualifying),
        "unresolved_primary_count": len(unresolved),
        "unresolved_best_score_bands_first_500": dict(score_bands),
        "unresolved_samples": unresolved[:500],
        "amount_samples": amount_entities[:200],
    }
    (evidence / "usaspending-postmortem.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dab-root", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    agent = load_candidate(args.candidate)
    civic = diagnose_civic(agent, args.dab_root, args.evidence)
    usa = diagnose_usaspending(agent, args.dab_root, args.evidence)
    summary = {
        "schema": "data-science-dominance/dab-postmortem-summary/2",
        "civic_parser_total_records": civic["parser_total_records"],
        "civic_ground_truth_names_found_in_documents": civic[
            "ground_truth_hit_count"
        ],
        "usa_candidate_count": usa["candidate_count"],
        "usa_ground_truth_count": usa["ground_truth_count"],
        "usa_dod_contract_rows": usa["dod_contract_rows"],
        "usa_candidate_exact_join_distinct_entities": usa[
            "candidate_exact_join_distinct_entities"
        ],
        "usa_primary_exact_join_distinct_entities": usa[
            "primary_exact_join_distinct_entities"
        ],
        "usa_unresolved_primary_count": usa["unresolved_primary_count"],
    }
    (args.evidence / "postmortem-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
