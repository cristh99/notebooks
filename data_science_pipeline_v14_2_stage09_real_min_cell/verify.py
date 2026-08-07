from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import stage09_real as s

HERE = Path(__file__).resolve().parent
FREEZE = HERE / "FREEZE.json"
RESULT = HERE / "LOCAL_RESULT.json"
CONTRACT = HERE / "ANALYSIS_CONTRACT_V14_1.json"
SNAPSHOT = HERE / "REAL_SEMANTIC_SNAPSHOT.json"
BINDING = HERE / "COMPATIBILITY_BINDING.json"


def canonical(value: Any) -> bytes:
    return s.canonical_bytes(value)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def verify_freeze() -> dict[str, Any]:
    raw = FREEZE.read_bytes()
    freeze = json.loads(raw)
    require(raw == canonical(freeze), "FREEZE.json is not canonical")
    require(freeze["schema"] == "data-science-pipeline/stage09-real-canary-freeze/1", "freeze schema mismatch")
    require(freeze["coordination_id"] == "COORD-2026-08-06-PARALLEL-V2", "coordination mismatch")
    for name, expected in freeze["file_sha256"].items():
        path = HERE / name
        require(path.is_file(), f"missing frozen file: {name}")
        require(sha(path) == expected, f"frozen hash mismatch: {name}")
    require(freeze["analysis_contract_sha256"] == s.ANALYSIS_CONTRACT_SHA256, "contract commitment mismatch")
    require(freeze["semantic_snapshot_sha256"] == s.SEMANTIC_SNAPSHOT_SHA256, "snapshot commitment mismatch")
    for field in ("production_modified", "mass_processing_authorized", "merge_authorized", "stage10_unblocked"):
        require(freeze[field] is False, f"{field} must remain false")
    require(freeze["external_cost_usd"] == 0.0, "external cost must be zero")
    return freeze


def run_tests() -> str:
    process = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "test_stage09_real.py"],
        cwd=HERE,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        check=False,
    )
    require(process.returncode == 0, process.stdout)
    require("Ran 60 tests" in process.stdout, "unexpected test count")
    require("\nOK" in process.stdout or process.stdout.rstrip().endswith("OK"), "test suite did not end OK")
    return process.stdout


def verify_result() -> dict[str, Any]:
    expected_raw = RESULT.read_bytes()
    expected = json.loads(expected_raw)
    require(expected_raw == canonical(expected), "LOCAL_RESULT.json is not canonical")
    with tempfile.TemporaryDirectory() as directory:
        replay = Path(directory) / "replay.json"
        observed = s.execute(CONTRACT, SNAPSHOT, BINDING, replay)
        require(replay.read_bytes() == expected_raw, "byte-identical replay failed")
        require(observed == expected, "semantic replay mismatch")
    require(expected["terminal_state"] == "ANALYSIS_NOT_EVALUABLE", "terminal mismatch")
    require(expected["terminal_detail"] == "ANALYSIS_NOT_EVALUABLE_MINIMUM_CELL_SIZE", "terminal detail mismatch")
    require(expected["gates"]["inferential_execution_allowed"] is False, "inferential execution unexpectedly allowed")
    require(expected["hypothesis_results"][0]["inferential_outputs_emitted"] == 0, "inferential outputs emitted")
    require(expected["population"]["eligible_contract_records"] == 1, "eligible contract count mismatch")
    require(expected["population"]["excluded_non_contract_records"] == 1, "excluded count mismatch")
    require(expected["population"]["group_counts"] == {"DIRECT": 0, "OPEN": 1}, "group counts mismatch")
    require(expected["population"]["missing_outcome_counts"] == {"DIRECT": 0, "OPEN": 1}, "missing outcome counts mismatch")
    require(not s.contains_forbidden_key(expected), "forbidden output key detected")
    require(sum(expected["claim_boundary"].values()) == 0, "claim boundary violated")
    require(expected["governance"]["stage10_global_unblocked"] is False, "Stage 10 globally unblocked")
    require(expected["governance"]["production_modified"] is False, "production modified")
    return expected


def build_receipt() -> dict[str, Any]:
    freeze = verify_freeze()
    test_log = run_tests()
    result = verify_result()
    checks = {
        "analysis_contract_exact_sha256": sha(CONTRACT) == s.ANALYSIS_CONTRACT_SHA256,
        "semantic_snapshot_exact_sha256": sha(SNAPSHOT) == s.SEMANTIC_SNAPSHOT_SHA256,
        "compatibility_binding_exact_scope": result["gates"]["exact_snapshot_compatibility_binding"] is True,
        "preregistration_unchanged": (
            result["preregistration"]["hypothesis_changed"] is False
            and result["preregistration"]["statistics_changed"] is False
            and result["preregistration"]["threshold_changed"] is False
        ),
        "semantic_terminal_valid": result["gates"]["semantic_terminal_valid"] is True,
        "quarantine_empty": result["gates"]["quarantine_empty"] is True,
        "role_separation": result["gates"]["role_separation"] is True,
        "input_conservation": result["population"]["input_conservation_observed"] is True,
        "payment_excluded": result["population"]["excluded_event_roles"] == ["PAYMENT"],
        "minimum_cell_gate_closed": result["gates"]["minimum_cell_gate"] is False,
        "complete_outcome_gate_closed": result["gates"]["complete_outcome_gate"] is False,
        "both_groups_gate_closed": result["gates"]["both_preregistered_groups_present"] is False,
        "inferential_execution_blocked": result["gates"]["inferential_execution_allowed"] is False,
        "inferential_outputs_zero": result["hypothesis_results"][0]["inferential_outputs_emitted"] == 0,
        "negative_control_not_promoted": result["negative_control"]["promoted"] is False,
        "multiplicity_not_applied": result["multiplicity"]["eligible_hypotheses"] == 0,
        "amount_review_candidates_zero": result["amount_diagnostics"]["review_candidates_emitted"] == 0,
        "causal_wrongdoing_ranking_claims_zero": sum(result["claim_boundary"].values()) == 0,
        "byte_identical_replay": True,
        "tests_60_of_60": "Ran 60 tests" in test_log,
        "external_cost_zero": result["governance"]["external_cost_usd"] == 0.0,
        "production_unmodified": result["governance"]["production_modified"] is False,
        "merge_unauthorized": result["governance"]["merge_authorized"] is False,
        "stage10_blocked": result["governance"]["stage10_global_unblocked"] is False,
    }
    require(all(checks.values()), f"verification checks failed: {checks}")
    receipt = {
        "schema": "data-science-pipeline/stage09-real-canary-verification-receipt/1",
        "verdict": "PASS_STAGE09_REAL_CANARY_FAIL_CLOSED_MINIMUM_CELL",
        "coordination_id": freeze["coordination_id"],
        "checks": checks,
        "tests": "60/60 PASS",
        "analysis_contract_sha256": s.ANALYSIS_CONTRACT_SHA256,
        "semantic_snapshot_sha256": s.SEMANTIC_SNAPSHOT_SHA256,
        "compatibility_binding_sha256": sha(BINDING),
        "result_file_sha256": sha(RESULT),
        "result_payload_sha256": result["result_sha256"],
        "terminal_state": result["terminal_state"],
        "terminal_detail": result["terminal_detail"],
        "eligible_contract_records": result["population"]["eligible_contract_records"],
        "excluded_payment_records": result["population"]["excluded_non_contract_records"],
        "group_counts": result["population"]["group_counts"],
        "missing_outcome_counts": result["population"]["missing_outcome_counts"],
        "inferential_outputs_emitted": 0,
        "scientific_promotion_credit": 0,
        "external_real_data_evaluations": 1,
        "external_cost_usd": 0.0,
        "production_modified": False,
        "mass_processing_authorized": False,
        "merge_authorized": False,
        "stage10_canary_input_ready": False,
        "stage10_global_unblocked": False,
        "claim_limit": "One exact PR149 two-row Stage 09 canary only. The preregistered inferential analysis is not evaluable because the minimum-cell, complete-outcome, and both-group gates fail. No association estimate, causal claim, wrongdoing label, public ranking, relationship assertion, documentary claim, production readiness, or corpus-wide validity is established.",
    }
    receipt["receipt_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(receipt))
    print(receipt["verdict"])


if __name__ == "__main__":
    main()
