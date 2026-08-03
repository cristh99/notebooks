from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "fin-rvi-002/g09-claim-scope-audit/2"
CLAIM_ID = "FIN-RVI-002-C1-BOUNDED"
REQUIRED_CHECKS = {
    "country_and_period_explicit",
    "source_publications_explicit",
    "maximum_claim_explicit",
    "strong_baseline_explicit",
    "policy_version_explicit",
    "one_to_many_cardinality_preserved",
    "unsupported_promotion_is_primary_safety_metric",
    "supported_recovery_is_guardrail",
    "permutation_falsifier_declared",
    "code_disjoint_replication_declared",
    "clean_reconstruction_declared",
    "independent_policy_implementation_declared",
    "general_technique_novelty_disclaimed",
    "legal_and_misconduct_claims_disclaimed",
    "no_exact_hit_not_equated_with_global_novelty",
}


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def verify(audit: Mapping[str, Any], root: Path | None = None) -> list[str]:
    root = root or Path(".")
    errors: list[str] = []
    if audit.get("schema") != SCHEMA:
        errors.append("schema")
    if audit.get("claim_id") != CLAIM_ID:
        errors.append("claim-id")
    if audit.get("verdict") != "PASS":
        errors.append("verdict")
    contract_path = audit.get("claim_contract")
    prior_path = audit.get("prior_art_closure")
    if not isinstance(contract_path, str) or not (root / contract_path).exists():
        errors.append("contract-file")
        contract = {}
    else:
        contract = json.loads((root / contract_path).read_text(encoding="utf-8"))
    if not isinstance(prior_path, str) or not (root / prior_path).exists():
        errors.append("prior-art-file")
        prior = {}
    else:
        prior = json.loads((root / prior_path).read_text(encoding="utf-8"))
    if contract.get("claim_id") != audit.get("claim_id"):
        errors.append("contract-claim-id")
    if prior.get("claim_id") != audit.get("claim_id"):
        errors.append("prior-claim-id")

    included = audit.get("included_scope")
    included = included if isinstance(included, Mapping) else {}
    contract_scope = contract.get("scope")
    contract_scope = contract_scope if isinstance(contract_scope, Mapping) else {}
    if included.get("country") != contract_scope.get("country"):
        errors.append("country")
    if included.get("period") != contract_scope.get("period"):
        errors.append("period")
    if included.get("sources") != contract_scope.get("sources"):
        errors.append("sources")
    if included.get("maximum_claim") != contract_scope.get("claim_level"):
        errors.append("maximum-claim")
    if included.get("policy") != contract.get("challenger"):
        errors.append("policy")
    if included.get("baseline") != contract.get("strong_baseline"):
        errors.append("baseline")
    if set(audit.get("excluded_claims", ())) != set(
        contract_scope.get("excluded_claims", ())
    ):
        errors.append("excluded-claims")
    boundary = contract.get("prior_art_boundary")
    boundary = boundary if isinstance(boundary, Mapping) else {}
    if set(audit.get("absorbed_prior_art", ())) != set(
        boundary.get("absorbed_components", ())
    ):
        errors.append("absorbed-prior-art")

    checks = audit.get("checks")
    checks = checks if isinstance(checks, Mapping) else {}
    if set(checks) != REQUIRED_CHECKS:
        errors.append("checks-shape")
    if not all(checks.get(name) is True for name in REQUIRED_CHECKS):
        errors.append("checks-failed")
    boundary_text = str(audit.get("boundary", "")).lower()
    for phrase in (
        "bounded empirical",
        "component methods",
        "legal",
        "fraud",
        "corruption",
        "global-universality",
    ):
        if phrase not in boundary_text:
            errors.append("boundary")
            break
    if "not proof of global novelty" not in str(prior.get("interpretation", "")):
        errors.append("prior-art-caution")
    return sorted(set(errors))


def build_receipt(audit: Mapping[str, Any], root: Path | None = None) -> dict[str, Any]:
    errors = verify(audit, root)
    payload = {
        "schema": "fin-rvi-002/g09-claim-scope-audit-receipt/2",
        "claim_id": audit.get("claim_id"),
        "audit_sha256": digest(audit),
        "valid": not errors,
        "errors": errors,
        "verdict": "PASS" if not errors else "FAIL",
    }
    return {"payload": payload, "sha256": digest(payload)}


def main() -> int:
    source = Path("fin_rvi_002_g09/claim_scope_audit_v2.json")
    audit = json.loads(source.read_text(encoding="utf-8"))
    receipt = build_receipt(audit, Path("."))
    output = Path("reports/fin_rvi_002_g09_v3")
    output.mkdir(parents=True, exist_ok=True)
    (output / "scope_audit_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["payload"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
