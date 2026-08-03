from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from . import run_stage1 as base
from .identity_v2 import adjudicate_object_v2, compact_identity_pairs_v2
from .ocds import closest_amount, closest_days, sha256_payload

SEPARATOR = "\u241f"
SEED = base.SEED + "-CARDINALITY-PRESERVING-V2"


def generate_candidates_v2(connection, amount_tolerance: float, max_days: int) -> list[dict[str, Any]]:
    del amount_tolerance
    candidates: dict[tuple[int, int], dict[str, Any]] = {}
    query = """
    SELECT
      o.release_pk,
      s.release_pk,
      o.composite_key,
      o.identity_basis,
      s.identity_basis
    FROM party_pairs AS o
    JOIN party_pairs AS s
      ON ABS(s.source_year - o.source_year) <= 1
     AND s.composite_key = o.composite_key
    JOIN releases AS ro ON ro.release_pk = o.release_pk
    JOIN releases AS rs ON rs.release_pk = s.release_pk
    WHERE o.source = 'ONCAE'
      AND s.source = 'SEFIN'
      AND o.identity_basis LIKE '%_CODE'
      AND s.identity_basis LIKE '%_CODE'
      AND ro.min_day IS NOT NULL
      AND rs.min_day IS NOT NULL
      AND ro.max_day >= rs.min_day - ?
      AND rs.max_day >= ro.min_day - ?
    """
    cursor = connection.execute(query, (max_days, max_days))
    cache = {}

    def summary(pk: int):
        if pk not in cache:
            cache[pk] = base.load_summary(connection, pk)
        return cache[pk]

    for oncae_pk, sefin_pk, composite_key, left_basis, right_basis in cursor:
        pair_key = (int(oncae_pk), int(sefin_pk))
        left = summary(pair_key[0])
        right = summary(pair_key[1])
        days = closest_days(left.dates, right.dates)
        if days is None or days > max_days:
            continue
        amount_match = closest_amount(left.amounts, right.amounts)
        if amount_match is None:
            continue
        shared_code = composite_key.split(SEPARATOR, 1)[1]
        candidate = {
            "oncae_release_pk": pair_key[0],
            "sefin_release_pk": pair_key[1],
            "ocid_oncae": left.ocid,
            "ocid_sefin": right.ocid,
            "source_year": left.source_year,
            "sefin_year": right.source_year,
            "identity_basis": min(left_basis, right_basis),
            "shared_code": shared_code,
            "amount_oncae": amount_match[1],
            "amount_sefin": amount_match[2],
            "relative_amount_difference": round(amount_match[0], 8),
            "absolute_days": days,
            "linkage_rule": "CANONICAL_BUYER_ALIAS_AND_SHARED_CODE",
        }
        candidate["candidate_id"] = sha256_payload(candidate)
        previous = candidates.get(pair_key)
        if previous is None or (candidate["shared_code"], candidate["absolute_days"]) < (
            previous["shared_code"], previous["absolute_days"]
        ):
            candidates[pair_key] = candidate

    output = list(candidates.values())
    by_oncae = Counter(item["oncae_release_pk"] for item in output)
    by_sefin = Counter(item["sefin_release_pk"] for item in output)
    for item in output:
        item["candidates_for_oncae"] = by_oncae[item["oncae_release_pk"]]
        item["candidates_for_sefin"] = by_sefin[item["sefin_release_pk"]]
        left_count = item["candidates_for_oncae"]
        right_count = item["candidates_for_sefin"]
        if left_count == 1 and right_count == 1:
            cardinality = "ONE_TO_ONE"
        elif left_count > 1 and right_count == 1:
            cardinality = "ONE_ONCAE_TO_MANY_SEFIN"
        elif left_count == 1 and right_count > 1:
            cardinality = "MANY_ONCAE_TO_ONE_SEFIN"
        else:
            cardinality = "MANY_TO_MANY"
        item["cardinality_type"] = cardinality
        item["linkage_status"] = (
            "STRICT_1_TO_1" if cardinality == "ONE_TO_ONE" else "AMBIGUOUS"
        )
    return sorted(output, key=lambda item: item["candidate_id"])


def freeze_holdout_v2(candidates: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Freeze a blind holdout while preserving real payment cardinality.

    Half of the capacity is allocated to breadth (one pair per shared code),
    and half to additional pairs from codes with multiple financial events.
    Selection uses only code/cardinality and a fixed hash seed; supplier and
    object evidence are not inspected.
    """
    if size <= 0:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        candidate["holdout_order_key"] = hashlib.sha256(
            f"{candidate['candidate_id']}|{SEED}".encode("utf-8")
        ).hexdigest()
        grouped.setdefault(candidate["shared_code"], []).append(candidate)
    for group in grouped.values():
        group.sort(key=lambda item: item["holdout_order_key"])

    code_order = sorted(
        grouped,
        key=lambda code: hashlib.sha256(f"{code}|{SEED}".encode("utf-8")).hexdigest(),
    )
    breadth_target = min((size + 1) // 2, len(code_order))
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for code in code_order[:breadth_target]:
        candidate = dict(grouped[code][0])
        candidate["holdout_stratum"] = "BREADTH_FIRST_PER_CODE"
        selected.append(candidate)
        selected_ids.add(candidate["candidate_id"])

    ambiguity_pool: list[dict[str, Any]] = []
    for code in code_order:
        for candidate in grouped[code][1:]:
            item = dict(candidate)
            item["holdout_stratum"] = "WITHIN_CODE_AMBIGUITY"
            ambiguity_pool.append(item)
    ambiguity_pool.sort(key=lambda item: item["holdout_order_key"])
    for candidate in ambiguity_pool:
        if len(selected) >= size:
            break
        if candidate["candidate_id"] not in selected_ids:
            selected.append(candidate)
            selected_ids.add(candidate["candidate_id"])

    fallback_pool = [
        dict(candidate)
        for candidate in candidates
        if candidate["candidate_id"] not in selected_ids
    ]
    fallback_pool.sort(key=lambda item: item["holdout_order_key"])
    for candidate in fallback_pool:
        if len(selected) >= size:
            break
        candidate["holdout_stratum"] = "DETERMINISTIC_FILL"
        selected.append(candidate)
        selected_ids.add(candidate["candidate_id"])

    selected.sort(key=lambda item: item["holdout_order_key"])
    return selected[:size]


def _rewrite_report(output: Path) -> None:
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = report["payload"]
    payload["schema"] = "fin-rvi-002/stage1-public-data/2"
    payload["configuration"]["selection_blinding"] = (
        "canonical buyer alias + exact shared contract/project code + cardinality only; supplier identity and object text evaluated after freeze"
    )
    payload["configuration"]["holdout_design"] = (
        "50% breadth across shared codes, then within-code ambiguity, then deterministic fill; all ordered by fixed SHA-256 seed"
    )
    payload["candidate_reconstruction"]["rule"] = (
        "same or adjacent year + canonical buyer alias + exact shared contract/project code; amount and date retained as diagnostics; <=366-day temporal gate"
    )
    payload["candidate_reconstruction"]["identity_grammar"] = (
        "SIT/FHIS-SEDECOAS/ENP institutional aliases, normalized buyer cores, exact contract/project codes"
    )
    decisions_path = output / "holdout_decisions.jsonl"
    decision_rows = [
        json.loads(line)
        for line in decisions_path.read_text(encoding="utf-8").splitlines()
        if line
    ] if decisions_path.exists() else []
    payload["holdout_metrics"]["cardinality_counts"] = dict(
        Counter(row.get("cardinality_type", "UNKNOWN") for row in decision_rows)
    )
    payload["holdout_metrics"]["stratum_counts"] = dict(
        Counter(row.get("holdout_stratum", "UNKNOWN") for row in decision_rows)
    )
    payload["holdout_metrics"]["unique_shared_codes"] = len(
        {row.get("shared_code") for row in decision_rows if row.get("shared_code")}
    )
    report["sha256"] = sha256_payload(payload)
    base.write_json(report_path, report)
    (output / "report.md").write_text(
        base.build_markdown({**payload, "sha256": report["sha256"]}), encoding="utf-8"
    )
    (output / "report.sha256").write_text(
        f"{base.sha256_file(report_path)}  report.json\n", encoding="utf-8"
    )

    decisions = decision_rows
    replay_payload = json.loads(json.dumps(payload))
    for record in replay_payload.get("downloads", []):
        for key in ("seconds", "attempt", "cached", "path"):
            record.pop(key, None)
    for record in replay_payload.get("dataset_stats", []):
        record.pop("seconds", None)
    replay_payload.get("holdout_metrics", {}).pop("document_acquisition_seconds", None)
    for decision in decisions:
        acquisition = decision.get("document_acquisition")
        if isinstance(acquisition, dict):
            acquisition.pop("seconds", None)
    deterministic = {
        "schema": "fin-rvi-002/stage1-deterministic-replay/2",
        "report_payload_without_timing": replay_payload,
        "holdout_decisions": decisions,
    }
    deterministic["sha256"] = sha256_payload(deterministic)
    base.write_json(output / "deterministic_replay.json", deterministic)


def main() -> None:
    base.compact_identity_pairs = compact_identity_pairs_v2
    base.generate_candidates = generate_candidates_v2
    base.freeze_holdout = freeze_holdout_v2
    base.adjudicate_object = adjudicate_object_v2
    output = Path("reports/fin_rvi_002_stage1")
    if "--output" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--output") + 1])
    try:
        base.main()
    except SystemExit as exc:
        if exc.code not in (None, 0, 2):
            raise
    _rewrite_report(output)


if __name__ == "__main__":
    main()
