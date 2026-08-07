from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


class GateError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _role(value: Any) -> str:
    return str(value or "").strip().upper()


def _method(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"DIRECT", "OPEN"}:
        return text
    return None


def semantic_records(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for item in _dicts(snapshot):
        required = {"event_role", "amount_role", "date_role"}
        if not required.issubset(item):
            continue
        event_id = str(item.get("event_id") or item.get("semantic_event_id") or "").strip()
        if not event_id:
            continue
        normalized = dict(item)
        key = sha256_value(normalized)
        candidates[key] = normalized
    records = sorted(candidates.values(), key=lambda row: (str(row.get("event_id", "")), sha256_value(row)))
    if not records:
        raise GateError("NO_SEMANTIC_EVENT_RECORDS")
    event_ids = [str(row.get("event_id") or row.get("semantic_event_id")) for row in records]
    if len(event_ids) != len(set(event_ids)):
        raise GateError("DUPLICATE_SEMANTIC_EVENT_ID")
    return records


def analyse(snapshot: dict[str, Any], contract: dict[str, Any], *, input_sha256: str) -> dict[str, Any]:
    expected = contract["input"]
    if input_sha256 != expected["snapshot_sha256"]:
        raise GateError("SEMANTIC_SNAPSHOT_SHA256_MISMATCH")
    records = semantic_records(snapshot)
    if len(records) != int(expected["expected_rows"]):
        raise GateError("SEMANTIC_ROW_COUNT_MISMATCH")

    population = contract["population"]
    contract_rows = [
        row for row in records
        if _role(row.get("event_role")) == population["event_role"]
        and _role(row.get("amount_role")) == population["amount_role"]
        and _role(row.get("date_role")) == population["date_role"]
    ]
    excluded_rows = [row for row in records if row not in contract_rows]
    groups = list(population["groups"])
    population_counts = {group: 0 for group in groups}
    evaluable_counts = {group: 0 for group in groups}
    missing_outcome_rows = 0
    unsupported_method_rows = 0

    for row in contract_rows:
        method = _method(row.get("procurement_method"))
        outcome = row.get(population["outcome"])
        if method is None:
            unsupported_method_rows += 1
            continue
        population_counts[method] += 1
        if isinstance(outcome, bool):
            evaluable_counts[method] += 1
        else:
            missing_outcome_rows += 1

    minimum_cell_n = int(population["minimum_cell_n"])
    minimum_observed_evaluable_cell = min(evaluable_counts.values()) if evaluable_counts else 0
    if minimum_observed_evaluable_cell >= minimum_cell_n:
        raise GateError("MINIMUM_CELL_PRECONDITION_UNEXPECTEDLY_MET_IN_BOUNDED_CANARY")

    record_commitments = sorted(sha256_value(row) for row in records)
    contract_commitments = sorted(sha256_value(row) for row in contract_rows)
    excluded_role_counts: dict[str, int] = {}
    for row in excluded_rows:
        role = _role(row.get("event_role")) or "UNKNOWN"
        excluded_role_counts[role] = excluded_role_counts.get(role, 0) + 1

    result = {
        "schema": "data-science-pipeline/analyze-real-min-cell-result/1",
        "coordination_id": contract["coordination_id"],
        "stage": contract["stage"],
        "verdict": contract["expected_terminal"]["verdict"],
        "terminal_state": contract["expected_terminal"]["terminal_state"],
        "reason_code": contract["expected_terminal"]["reason_code"],
        "input": {
            "semantic_pr": expected["pr"],
            "semantic_artifact_id": expected["artifact_id"],
            "semantic_snapshot_sha256": input_sha256,
            "semantic_row_count": len(records),
            "record_commitments_sha256": record_commitments,
        },
        "population": {
            "event_role": population["event_role"],
            "amount_role": population["amount_role"],
            "date_role": population["date_role"],
            "eligible_contract_rows": len(contract_rows),
            "excluded_rows": len(excluded_rows),
            "excluded_role_counts": dict(sorted(excluded_role_counts.items())),
            "eligible_record_commitments_sha256": contract_commitments,
            "registered_groups": groups,
            "group_population_counts": population_counts,
            "group_evaluable_outcome_counts": evaluable_counts,
            "minimum_cell_n": minimum_cell_n,
            "minimum_observed_evaluable_cell_n": minimum_observed_evaluable_cell,
            "missing_outcome_rows": missing_outcome_rows,
            "unsupported_method_rows": unsupported_method_rows,
        },
        "registered_analysis": {
            "hypothesis_id": "H09-001",
            "baseline_id": "B09-POOLED-RATE",
            "test": contract["statistics"]["primary_test"],
            "uncertainty": contract["statistics"]["uncertainty"],
            "multiplicity": contract["statistics"]["fdr_method"],
            "fdr_q": contract["statistics"]["fdr_q"],
            "executed": False,
        },
        "statistical_outputs": {
            "p_value": None,
            "risk_difference": None,
            "confidence_interval": None,
            "q_value": None,
            "negative_control_p_value": None,
            "outlier_candidates": None,
        },
        "guardrails": {
            "payment_excluded_from_contract_population": "PAYMENT" in excluded_role_counts,
            "cross_role_amount_aggregation_performed": False,
            "low_competition_imputed": False,
            "raw_identity_exported": False,
            "ranking_emitted": False,
            "causal_claim_emitted": False,
            "wrongdoing_label_emitted": False,
            "relationship_record_included": False,
            "documentary_candidate_included": False,
        },
        "readiness": {
            "stage09_canary_completed": True,
            "analysis_evaluable": False,
            "stage10_canary_input_ready": False,
            "stage10_global_unblocked": False,
            "next_gate": "preregistered_scale_up_with_at_least_five_evaluable_contract_events_in_each_registered_method_group",
        },
        "governance": contract["governance"],
    }
    return result


def run(contract_path: Path, input_path: Path, output_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text())
    input_bytes = input_path.read_bytes()
    snapshot = json.loads(input_bytes)
    result = analyse(snapshot, contract, input_sha256=sha256_bytes(input_bytes))
    output_path.write_bytes(canonical_bytes(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.contract, args.input, args.output)
    print(result["verdict"])


if __name__ == "__main__":
    main()
