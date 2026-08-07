from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

ANALYSIS_CONTRACT_SHA256 = "d0e94b6d1c558132cfc1d35e988b6219cd4eda28865320801b75ab780ea7600c"
SEMANTIC_SNAPSHOT_SHA256 = "f2032c782da735cafe4bb29d76f49f04fbd580a8d810f59a77d588908271371b"
ANALYSIS_CONTRACT_SCHEMA = "data-science-pipeline/analyze-contract/3"
OBSERVED_SNAPSHOT_SCHEMA = "data-science-pipeline/semantic-snapshot/3"
LEGACY_REQUIRED_SNAPSHOT_SCHEMA = "data-science-pipeline/semantic-snapshot/2"
BINDING_SCHEMA = "data-science-pipeline/analyze-input-compatibility-binding/1"
RESULT_SCHEMA = "data-science-pipeline/analyze-real-canary/1"
ALLOWED_RESOLUTION_STATES = {"MATCH_OFFICIAL", "MATCH_VALIDATED"}
METHOD_MAP = {"open": "OPEN", "direct": "DIRECT"}
FORBIDDEN_OUTPUT_KEYS = {
    "p_value", "pvalue", "fisher_exact", "risk_difference", "effect_size",
    "confidence_interval", "ci_lower", "ci_upper", "q_value", "adjusted_p_value",
    "association_promoted", "causal_effect", "wrongdoing", "fraud", "corruption",
    "ranking", "rank", "outlier_score",
}


class ContractError(ValueError):
    pass


class BindingError(ValueError):
    pass


class SnapshotError(ValueError):
    pass


def require(condition: bool, message: str, exc: type[ValueError] = ValueError) -> None:
    if not condition:
        raise exc(message)


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def require_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        require(math.isfinite(value), f"non-finite number at {path}")
    elif isinstance(value, dict):
        for key, child in value.items():
            require_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            require_finite(child, f"{path}[{index}]")


def strict_loads(text: str) -> Any:
    value = json.loads(text, parse_constant=reject_constant)
    require_finite(value)
    return value


def canonical_bytes(value: Any) -> bytes:
    require_finite(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_canonical_json(path: Path, expected_sha256: str, exc: type[ValueError]) -> dict[str, Any]:
    raw = path.read_bytes()
    require(sha256_bytes(raw) == expected_sha256, f"SHA-256 mismatch: {path.name}", exc)
    value = strict_loads(raw.decode("utf-8"))
    require(isinstance(value, dict), f"{path.name} is not an object", exc)
    require(raw == canonical_bytes(value), f"{path.name} is not canonical JSON", exc)
    return value


def load_binding(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = strict_loads(raw.decode("utf-8"))
    require(isinstance(value, dict), "binding is not an object", BindingError)
    require(raw == canonical_bytes(value), "binding is not canonical JSON", BindingError)
    require(value.get("schema") == BINDING_SCHEMA, "binding schema mismatch", BindingError)
    require(value.get("analysis_contract_sha256") == ANALYSIS_CONTRACT_SHA256, "contract binding mismatch", BindingError)
    require(value.get("semantic_snapshot_sha256") == SEMANTIC_SNAPSHOT_SHA256, "snapshot binding mismatch", BindingError)
    require(value.get("legacy_required_snapshot_schema") == LEGACY_REQUIRED_SNAPSHOT_SCHEMA, "legacy schema mismatch", BindingError)
    require(value.get("observed_snapshot_schema") == OBSERVED_SNAPSHOT_SCHEMA, "observed schema mismatch", BindingError)
    require(value.get("scope") == "EXACT_PR149_SNAPSHOT_ONLY", "binding scope is not exact", BindingError)
    require(value.get("data_transformation_performed") is False, "binding may not transform data", BindingError)
    require(value.get("hypothesis_changed") is False, "hypothesis changed", BindingError)
    require(value.get("statistics_changed") is False, "statistics changed", BindingError)
    require(value.get("threshold_changed") is False, "threshold changed", BindingError)
    require(value.get("method_mapping") == {"direct": "DIRECT", "open": "OPEN"}, "method mapping mismatch", BindingError)
    require(value.get("stage10_unblocked") is False, "Stage 10 may not be unblocked", BindingError)
    return value


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema") == ANALYSIS_CONTRACT_SCHEMA, "analysis contract schema mismatch", ContractError)
    require(contract.get("stage") == "09 — Analyze", "analysis stage mismatch", ContractError)
    population = contract.get("analysis_population", {})
    require(
        population
        == {
            "amount_role": "CONTRACT_VALUE",
            "date_role": "CONTRACT_DATE",
            "event_role": "CONTRACT",
            "excluded_role_policy": "report_explicitly_never_aggregate_across_roles",
        },
        "analysis population drift",
        ContractError,
    )
    hypotheses = contract.get("hypotheses")
    require(isinstance(hypotheses, list) and len(hypotheses) == 1, "hypothesis count mismatch", ContractError)
    hypothesis = hypotheses[0]
    require(hypothesis.get("id") == "H09-001", "hypothesis ID mismatch", ContractError)
    require(hypothesis.get("groups") == ["DIRECT", "OPEN"], "hypothesis groups mismatch", ContractError)
    require(hypothesis.get("outcome") == "low_competition", "hypothesis outcome mismatch", ContractError)
    require(hypothesis.get("test") == "two_sided_fisher_exact", "hypothesis test mismatch", ContractError)
    require(hypothesis.get("effect") == "risk_difference_direct_minus_open", "effect mismatch", ContractError)
    require(hypothesis.get("causal") is False, "causal hypothesis forbidden", ContractError)
    stats = contract.get("statistics", {})
    require(stats.get("minimum_cell_n") == 5, "minimum cell threshold drift", ContractError)
    require(stats.get("confidence_level") == 0.95, "confidence level drift", ContractError)
    require(stats.get("fdr_method") == "Benjamini-Hochberg", "FDR method drift", ContractError)
    require(stats.get("fdr_q") == 0.05, "FDR q drift", ContractError)
    require(stats.get("model_selection_performed") is False, "model selection forbidden", ContractError)
    input_contract = contract.get("input_contract", {})
    require(input_contract.get("required_snapshot_schema") == LEGACY_REQUIRED_SNAPSHOT_SCHEMA, "legacy input schema drift", ContractError)
    require(input_contract.get("required_terminal_state") == "SEMANTIC_VALIDATED", "semantic terminal drift", ContractError)
    require(input_contract.get("required_currency") == "HNL", "currency drift", ContractError)
    require(input_contract.get("quarantine_must_be_empty") is True, "quarantine gate drift", ContractError)
    controls = contract.get("negative_controls")
    require(isinstance(controls, list) and len(controls) == 1, "negative control count mismatch", ContractError)
    require(controls[0].get("id") == "NC09-001" and controls[0].get("must_not_promote") is True, "negative control drift", ContractError)
    claims = contract.get("claim_policy", {})
    for field in ("causal_claims_forbidden", "wrongdoing_labels_forbidden", "public_rankings_forbidden"):
        require(claims.get(field) is True, f"claim guard missing: {field}", ContractError)
    governance = contract.get("governance", {})
    require(governance.get("external_cost_usd") == 0.0, "external cost drift", ContractError)
    for field in ("production_modified", "mass_processing_authorized", "merge_authorized", "stage10_unblocked"):
        require(governance.get(field) is False, f"governance drift: {field}", ContractError)


def validate_snapshot(snapshot: dict[str, Any], contract: dict[str, Any], binding: dict[str, Any]) -> None:
    require(snapshot.get("schema") == OBSERVED_SNAPSHOT_SCHEMA, "snapshot schema mismatch", SnapshotError)
    require(snapshot.get("stage") == "08 — Semantic", "snapshot stage mismatch", SnapshotError)
    require(snapshot.get("terminal_state") == contract["input_contract"]["required_terminal_state"], "snapshot terminal mismatch", SnapshotError)
    require(snapshot.get("coordination_id") == contract["coordination_id"], "coordination mismatch", SnapshotError)
    require(snapshot.get("grain") == binding["observed_grain"], "snapshot grain mismatch", SnapshotError)
    require(snapshot.get("analysis_cutoff") == "2025-12-31", "analysis cutoff mismatch", SnapshotError)
    require(snapshot.get("input_conservation_observed") is True, "input conservation missing", SnapshotError)
    require(snapshot.get("quarantine") == [], "snapshot quarantine is not empty", SnapshotError)
    governance = snapshot.get("governance", {})
    require(governance.get("stage09_canary_input_ready") is True, "Stage 09 canary input not ready", SnapshotError)
    require(governance.get("stage09_global_unblocked") is False, "global Stage 09 must remain blocked", SnapshotError)
    require(governance.get("production_modified") is False, "production modified upstream", SnapshotError)
    require(governance.get("merge_authorized") is False, "merge authorized upstream", SnapshotError)
    excluded = snapshot.get("excluded_surfaces", {})
    for field in (
        "cross_source_relationship_records_emitted",
        "documentary_candidate_records_emitted",
        "raw_identity_records_emitted",
        "input_receipt_payloads_emitted",
    ):
        require(excluded.get(field) == 0, f"excluded surface emitted: {field}", SnapshotError)
    claims = snapshot.get("claim_boundary", {})
    for field in (
        "human_claims_emitted",
        "identity_guesses",
        "causal_or_wrongdoing_claims",
        "cross_source_relationship_assertions",
        "documentary_match_claims",
    ):
        require(claims.get(field) == 0, f"upstream claim boundary violated: {field}", SnapshotError)
    records = snapshot.get("records")
    require(isinstance(records, list) and len(records) == 2, "expected exact two-row snapshot", SnapshotError)
    require(snapshot.get("counts", {}).get("input_rows") == 2, "input row count mismatch", SnapshotError)
    require(snapshot.get("counts", {}).get("eligible_records") == 2, "eligible row count mismatch", SnapshotError)
    require(len({row.get("event_id") for row in records}) == len(records), "duplicate event_id", SnapshotError)
    for row in records:
        require(row.get("currency") == "HNL", "non-HNL row", SnapshotError)
        require(row.get("resolution_state") in ALLOWED_RESOLUTION_STATES, "invalid resolution state", SnapshotError)
        require(isinstance(row.get("amount_hnl"), (int, float)) and not isinstance(row.get("amount_hnl"), bool), "invalid amount", SnapshotError)
        require(math.isfinite(float(row["amount_hnl"])) and float(row["amount_hnl"]) >= 0, "non-finite or negative amount", SnapshotError)
        require(row.get("low_competition") in (True, False, None), "invalid low_competition", SnapshotError)
        require(type(row.get("supplier_missing")) is bool, "invalid supplier_missing", SnapshotError)
        require(type(row.get("semantic_record_sha256")) is str and len(row["semantic_record_sha256"]) == 64, "invalid semantic record hash", SnapshotError)


def canonical_method(value: Any) -> str | None:
    if value is None:
        return None
    require(type(value) is str, "procurement method must be text", SnapshotError)
    normalized = value.strip().casefold()
    return METHOD_MAP.get(normalized)


def filter_population(records: Iterable[dict[str, Any]], contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    population = contract["analysis_population"]
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in records:
        reasons: list[str] = []
        if row.get("event_role") != population["event_role"]:
            reasons.append("EVENT_ROLE_EXCLUDED")
        if row.get("amount_role") != population["amount_role"]:
            reasons.append("AMOUNT_ROLE_EXCLUDED")
        if row.get("date_role") != population["date_role"]:
            reasons.append("DATE_ROLE_EXCLUDED")
        if row.get("currency") != contract["input_contract"]["required_currency"]:
            reasons.append("CURRENCY_EXCLUDED")
        if reasons:
            excluded.append({"semantic_record_sha256": row["semantic_record_sha256"], "reasons": sorted(reasons)})
        else:
            method = canonical_method(row.get("procurement_method"))
            require(method in {"DIRECT", "OPEN"}, "eligible contract method outside preregistered groups", SnapshotError)
            enriched = dict(row)
            enriched["analysis_method"] = method
            eligible.append(enriched)
    eligible.sort(key=lambda row: row["semantic_record_sha256"])
    excluded.sort(key=lambda row: row["semantic_record_sha256"])
    return eligible, excluded


def contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in FORBIDDEN_OUTPUT_KEYS:
                return True
            if contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(contains_forbidden_key(child) for child in value)
    return False


def build_result(contract: dict[str, Any], snapshot: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    validate_snapshot(snapshot, contract, binding)
    eligible, excluded = filter_population(snapshot["records"], contract)
    groups = ("DIRECT", "OPEN")
    group_counts = {group: sum(row["analysis_method"] == group for row in eligible) for group in groups}
    observed_outcome_counts = {
        group: sum(row["analysis_method"] == group and type(row["low_competition"]) is bool for row in eligible)
        for group in groups
    }
    missing_outcome_counts = {
        group: sum(row["analysis_method"] == group and row["low_competition"] is None for row in eligible)
        for group in groups
    }
    contingency_cells = {
        group: {
            "low_competition_true": sum(
                row["analysis_method"] == group and row["low_competition"] is True for row in eligible
            ),
            "low_competition_false": sum(
                row["analysis_method"] == group and row["low_competition"] is False for row in eligible
            ),
        }
        for group in groups
    }
    minimum_cell_n = contract["statistics"]["minimum_cell_n"]
    cells = [
        contingency_cells[group][outcome]
        for group in groups
        for outcome in ("low_competition_true", "low_competition_false")
    ]
    both_groups_present = all(group_counts[group] > 0 for group in groups)
    complete_outcome_gate = all(missing_outcome_counts[group] == 0 for group in groups)
    minimum_cell_gate = all(cell >= minimum_cell_n for cell in cells)
    inferential_allowed = both_groups_present and complete_outcome_gate and minimum_cell_gate

    reasons: list[str] = []
    if not both_groups_present:
        reasons.append("PREREGISTERED_GROUP_MISSING")
    if not complete_outcome_gate:
        reasons.append("OUTCOME_NOT_REPORTED_IN_SOURCE")
    if not minimum_cell_gate:
        reasons.append("MINIMUM_CELL_SIZE_NOT_MET")
    require(not inferential_allowed, "bounded canary unexpectedly passed inferential gates")

    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "stage": "09 — Analyze",
        "terminal_state": "ANALYSIS_NOT_EVALUABLE",
        "terminal_detail": "ANALYSIS_NOT_EVALUABLE_MINIMUM_CELL_SIZE",
        "coordination_id": contract["coordination_id"],
        "analysis_contract_sha256": ANALYSIS_CONTRACT_SHA256,
        "semantic_snapshot_sha256": SEMANTIC_SNAPSHOT_SHA256,
        "compatibility_binding_sha256": sha256_bytes(canonical_bytes(binding)),
        "preregistration": {
            "hypothesis_id": "H09-001",
            "groups": ["DIRECT", "OPEN"],
            "outcome": "low_competition",
            "test": "two_sided_fisher_exact",
            "effect": "risk_difference_direct_minus_open",
            "minimum_cell_n": minimum_cell_n,
            "hypothesis_changed": False,
            "statistics_changed": False,
            "threshold_changed": False,
        },
        "population": {
            "input_semantic_records": len(snapshot["records"]),
            "eligible_contract_records": len(eligible),
            "excluded_non_contract_records": len(excluded),
            "eligible_event_role": "CONTRACT",
            "eligible_amount_role": "CONTRACT_VALUE",
            "eligible_date_role": "CONTRACT_DATE",
            "excluded_event_roles": sorted({snapshot_row["event_role"] for snapshot_row in snapshot["records"] if snapshot_row["event_role"] != "CONTRACT"}),
            "group_counts": group_counts,
            "observed_outcome_counts": observed_outcome_counts,
            "missing_outcome_counts": missing_outcome_counts,
            "contingency_cells": contingency_cells,
            "input_conservation_observed": len(snapshot["records"]) == len(eligible) + len(excluded),
            "cross_role_amount_aggregation_performed": False,
        },
        "gates": {
            "exact_contract_hash": True,
            "exact_snapshot_hash": True,
            "exact_snapshot_compatibility_binding": True,
            "semantic_terminal_valid": True,
            "quarantine_empty": True,
            "role_separation": True,
            "both_preregistered_groups_present": both_groups_present,
            "complete_outcome_gate": complete_outcome_gate,
            "minimum_cell_gate": minimum_cell_gate,
            "inferential_execution_allowed": inferential_allowed,
        },
        "hypothesis_results": [
            {
                "id": "H09-001",
                "status": "NOT_EVALUATED",
                "reasons": sorted(reasons),
                "inferential_outputs_emitted": 0,
            }
        ],
        "multiplicity": {
            "method": "Benjamini-Hochberg",
            "status": "NOT_APPLIED_NO_ELIGIBLE_HYPOTHESIS",
            "eligible_hypotheses": 0,
        },
        "negative_control": {
            "id": "NC09-001",
            "status": "NOT_RUN_INFERENTIAL_GATE_CLOSED",
            "promoted": False,
        },
        "amount_diagnostics": {
            "method": "median/MAD modified z",
            "status": "NOT_RUN_MINIMUM_GROUP_N_NOT_MET",
            "review_candidates_emitted": 0,
        },
        "excluded_records": {
            "count": len(excluded),
            "commitments": [row["semantic_record_sha256"] for row in excluded],
            "raw_records_emitted": 0,
        },
        "claim_boundary": {
            "association_estimates_emitted": 0,
            "causal_claims_emitted": 0,
            "wrongdoing_labels_emitted": 0,
            "public_rankings_emitted": 0,
            "cross_source_relationship_assertions_emitted": 0,
            "documentary_match_claims_emitted": 0,
        },
        "governance": {
            "external_real_data_evaluations": 1,
            "external_cost_usd": 0.0,
            "production_modified": False,
            "mass_processing_authorized": False,
            "merge_authorized": False,
            "scientific_promotion_credit": 0,
            "stage10_canary_input_ready": False,
            "stage10_global_unblocked": False,
        },
    }
    require(result["population"]["input_conservation_observed"], "population conservation failed")
    require(not contains_forbidden_key(result), "forbidden inferential or claim key emitted")
    result["result_sha256"] = sha256_bytes(canonical_bytes(result))
    return result


def execute(contract_path: Path, snapshot_path: Path, binding_path: Path, output_path: Path) -> dict[str, Any]:
    contract = load_canonical_json(contract_path, ANALYSIS_CONTRACT_SHA256, ContractError)
    snapshot = load_canonical_json(snapshot_path, SEMANTIC_SNAPSHOT_SHA256, SnapshotError)
    binding = load_binding(binding_path)
    result = build_result(contract, snapshot, binding)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_bytes(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    execute(args.contract, args.snapshot, args.binding, args.output)


if __name__ == "__main__":
    main()
