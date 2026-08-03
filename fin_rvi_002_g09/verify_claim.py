from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

REQUIRED_ABSORBED = {
    "public_payment_record_linkage",
    "procurement_supplier_name_reconciliation",
    "procurement_spending_knowledge_graphs",
    "OCDS_contract_lifecycle_transactions_and_documents",
    "adaptive_costly_information_acquisition",
    "noisy_expensive_test_selection",
    "provenance_and_refutation",
    "one_to_many_procurement_data_modeling",
}
REQUIRED_EXCLUSIONS = {
    "legality",
    "fraud",
    "corruption",
    "physical receipt",
    "quality",
    "liquidation",
    "causal impact",
}
REQUIRED_GATES = {
    "stage2_strong_baseline",
    "clean_independent_replay",
    "second_sealed_cohort",
    "systematic_primary_prior_art_log",
    "claim_scope_audit",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def verify(contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema") != "fin-rvi-002/g09-claim-contract/1":
        errors.append("schema")
    if contract.get("claim_id") != "FIN-RVI-002-C1":
        errors.append("claim-id")
    if contract.get("status") not in {"OPEN", "PASS", "FALSIFIED", "UNDERSPECIFIED"}:
        errors.append("status")
    claim = str(contract.get("claim", ""))
    required_phrases = (
        "sealed public ONCAE-SEFIN holdout",
        "exact contract/project-code blocking",
        "compatible supplier identity",
        "strictly reduces unsupported promotions",
        "without reducing supported-payment recovery",
        "one-to-many contract-financial-event cardinality",
        "fail-closed abstention",
    )
    if any(phrase not in claim for phrase in required_phrases):
        errors.append("claim-specificity")

    scope = contract.get("scope")
    if not isinstance(scope, Mapping):
        errors.append("scope")
    else:
        if scope.get("country") != "Honduras":
            errors.append("country")
        if scope.get("period") != "2023-2025":
            errors.append("period")
        if scope.get("claim_level") != "CONTRACTOR_PAYMENT":
            errors.append("claim-level")
        if set(scope.get("excluded_claims", ())) != REQUIRED_EXCLUSIONS:
            errors.append("excluded-claims")

    if contract.get("strong_baseline") != "B1_CODE_SUPPLIER":
        errors.append("strong-baseline")
    if contract.get("challenger") != "POLICY_DOCUMENTARY":
        errors.append("challenger")
    if set(contract.get("prior_art_absorbed", ())) != REQUIRED_ABSORBED:
        errors.append("prior-art-boundary")

    required = contract.get("required_gates")
    current = contract.get("current_gates")
    if not isinstance(required, Mapping) or set(required) != REQUIRED_GATES:
        errors.append("required-gates")
    if not isinstance(current, Mapping) or set(current) != REQUIRED_GATES:
        errors.append("current-gates")
    if isinstance(required, Mapping) and any(value != "PASS" for value in required.values()):
        errors.append("gate-contract")

    if contract.get("status") == "PASS":
        if not isinstance(current, Mapping) or any(current.get(gate) != "PASS" for gate in REQUIRED_GATES):
            errors.append("premature-pass")
    if contract.get("status") == "OPEN":
        if isinstance(current, Mapping) and all(current.get(gate) == "PASS" for gate in REQUIRED_GATES):
            errors.append("stale-open")

    predictions = contract.get("exclusive_predictions")
    falsifiers = contract.get("falsifiers")
    if not isinstance(predictions, list) or len(predictions) < 6 or len(set(predictions)) != len(predictions):
        errors.append("predictions")
    if not isinstance(falsifiers, list) or len(falsifiers) < 7 or len(set(falsifiers)) != len(falsifiers):
        errors.append("falsifiers")

    sources = contract.get("primary_sources")
    if not isinstance(sources, list) or len(sources) < 6:
        errors.append("primary-sources")
    elif any(not isinstance(source, Mapping) or not source.get("title") or not source.get("absorbs") for source in sources):
        errors.append("primary-source-shape")
    return errors


def build_receipt(contract: Mapping[str, Any]) -> dict[str, Any]:
    errors = verify(contract)
    current = contract.get("current_gates", {})
    passed = sum(value == "PASS" for value in current.values()) if isinstance(current, Mapping) else 0
    return {
        "schema": "fin-rvi-002/g09-claim-receipt/1",
        "claim_id": contract.get("claim_id"),
        "contract_sha256": digest(contract),
        "valid": not errors,
        "errors": errors,
        "status": contract.get("status"),
        "passed_required_gates": passed,
        "total_required_gates": len(REQUIRED_GATES),
        "promotion_allowed": not errors and contract.get("status") == "PASS" and passed == len(REQUIRED_GATES),
    }


def main() -> int:
    source = Path("fin_rvi_002_g09/claim_contract.json")
    contract = json.loads(source.read_text(encoding="utf-8"))
    receipt = build_receipt(contract)
    output = Path("reports/fin_rvi_002_g09")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "claim_receipt.json"
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
