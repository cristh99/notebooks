from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

CONTRACT_SCHEMA = "fin-rvi-002/g09-final-contract/2"
CLAIM_ID = "FIN-RVI-002-C1-BOUNDED"
PRIOR_ART_SCHEMA = "fin-rvi-002/g09-prior-art-closure/2"
REQUIRED_EXCLUSIONS = {
    "legality",
    "fraud",
    "corruption",
    "physical receipt",
    "quality",
    "liquidation",
    "causal impact",
    "global universality",
    "novelty of entity resolution",
    "novelty of procurement knowledge graphs",
    "novelty of active evidence acquisition",
}
REQUIRED_ABSORBED = {
    "public payment ingestion and record linkage",
    "procurement supplier reconciliation",
    "procurement-company-spending knowledge graphs",
    "many-to-many purchase-to-pay cardinality",
    "documentary audit evidence for payment",
    "active and agentic evidence acquisition",
    "cost-aware sequential entity resolution",
    "provenance-bearing governed match assertions",
    "false-positive-aware procurement red flags",
    "contract-payment reconciliation and accounts-payable exception handling",
}
REQUIRED_GATES = {
    "g07_operational_utility",
    "stage4_independent_code_disjoint_cohort",
    "stage5_clean_reconstruction",
    "systematic_primary_prior_art_closure",
    "claim_scope_audit",
    "stage6_third_code_disjoint_cohort",
    "stage6_independent_policy_implementation",
    "stage7_third_cohort_clean_reconstruction",
}
ALLOWED_GATE_VALUES = {"PASS", "PENDING", "FAIL", "FALSIFIED"}
REQUIRED_CLAIM_PHRASES = (
    "multiple preregistered, mutually shared-code-disjoint",
    "public Honduras ONCAE-SEFIN cohorts",
    "exact contract/project-code blocking",
    "compatible supplier identity",
    "fixed fail-closed documentary policy",
    "maximum claim CONTRACTOR_PAYMENT",
    "reduces unsupported payment attribution",
    "without reducing recovery of supported payments",
    "one-to-many contract-payment cardinality",
    "independent policy implementation",
    "clean public reconstruction",
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _verify_stage4(value: Any) -> list[str]:
    errors: list[str] = []
    stage = _mapping(value)
    if stage is None:
        return ["stage4-shape"]
    exact = {
        "head_sha": "9e6686204fce20bc21d17f041d506a2a9c92761d",
        "run_id": 30841561243,
        "artifact_id": 8867231467,
        "artifact_sha256": "a1a4a2e7dd3a722ce9b1dac9b5dbe02a5bfde0f7bd63c9e5fb6974c056de3928",
        "cohort_rows": 120,
        "prior_shared_codes_excluded": 118,
    }
    for field, expected in exact.items():
        if stage.get(field) != expected:
            errors.append(f"stage4-{field}")
    if stage.get("labels") != {
        "SUPPORTED": 58,
        "REJECTED": 28,
        "UNRESOLVED": 34,
    }:
        errors.append("stage4-labels")
    baseline = _mapping(stage.get("baseline")) or {}
    challenger = _mapping(stage.get("challenger")) or {}
    permutation = _mapping(stage.get("permutation")) or {}
    if baseline.get("unsafe_overpromotions") != 20 or baseline.get(
        "supported_recovered"
    ) != 58:
        errors.append("stage4-baseline")
    if challenger != {
        "unsafe_overpromotions": 0,
        "supported_recovered": 58,
        "missed_supported": 0,
    }:
        errors.append("stage4-challenger")
    if permutation != {
        "unsafe_overpromotions": 21,
        "supported_recovered": 37,
    }:
        errors.append("stage4-permutation")
    return errors


def _verify_stage5(value: Any) -> list[str]:
    errors: list[str] = []
    stage = _mapping(value)
    if stage is None:
        return ["stage5-shape"]
    exact = {
        "head_sha": "d9928f064d0ff80084d46c9fae73d7717dffbfbd",
        "run_id": 30844453922,
        "artifact_id": 8868335548,
        "artifact_sha256": "53920001230a0ea13f3929f0abcdf529653759a8e869dd1707499029ba867462",
        "python_receipt_sha256": "03e97d0eb13ad7808a1a78f37ff2e8d16695ca092ccf3ed76f7cd12a78b795be",
        "node_receipt_sha256": "3fa82f11d111d97e3b5fcaf58680a413f1482e01744e336cd5e64fa0c33d72d6",
        "compact_rows_sha256": "5793b9d1f88176b9ba3b61a006510766041572502a6ad0595e05fc2869f71571",
        "labels_sha256": "949b6e8d0ad035130cb47d2e7c97a5f4176ea5d9bbcdb7dbc7b0444c22754a1f",
        "candidate_ids_sha256": "7352d9e05195fe597a4b8001192f39f7e540a0ee8799d0b0e940c73dff2354db",
        "g07": "PASS",
        "score_after": 920,
    }
    for field, expected in exact.items():
        if stage.get(field) != expected:
            errors.append(f"stage5-{field}")
    return errors


def _verify_stage6(value: Any, required: bool) -> list[str]:
    if value is None:
        return ["stage6-missing"] if required else []
    errors: list[str] = []
    stage = _mapping(value)
    if stage is None:
        return ["stage6-shape"]
    if stage.get("status") != "PASS":
        errors.append("stage6-status")
    if stage.get("cohort_rows") != 120:
        errors.append("stage6-cohort")
    if stage.get("prior_shared_codes_excluded") != 237:
        errors.append("stage6-code-exclusion")
    if stage.get("prior_shared_codes_sha256") != (
        "927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984"
    ):
        errors.append("stage6-code-exclusion-hash")
    baseline = _mapping(stage.get("baseline")) or {}
    challenger = _mapping(stage.get("challenger")) or {}
    if not isinstance(baseline.get("unsafe_overpromotions"), int) or baseline.get(
        "unsafe_overpromotions", 0
    ) <= 0:
        errors.append("stage6-baseline-unsafe")
    if challenger.get("unsafe_overpromotions") != 0:
        errors.append("stage6-unsafe")
    if challenger.get("missed_supported") != 0:
        errors.append("stage6-missed-supported")
    if challenger.get("supported_recovered") != baseline.get(
        "supported_recovered"
    ):
        errors.append("stage6-recovery")
    if stage.get("independent_policy_mismatches") != 0:
        errors.append("stage6-independent-policy")
    required_hashes = (
        "artifact_sha256",
        "report_payload_sha256",
        "compact_rows_sha256",
        "labels_sha256",
        "node_receipt_sha256",
        "independent_policy_decisions_sha256",
    )
    for field in required_hashes:
        value_field = stage.get(field)
        if not isinstance(value_field, str) or len(value_field) != 64:
            errors.append(f"stage6-{field}")
    return errors


def _verify_stage7(value: Any, required: bool) -> list[str]:
    if value is None:
        return ["stage7-missing"] if required else []
    errors: list[str] = []
    stage = _mapping(value)
    if stage is None:
        return ["stage7-shape"]
    if stage.get("status") != "PASS":
        errors.append("stage7-status")
    if stage.get("g09_replication") != "PASS":
        errors.append("stage7-g09-replication")
    if stage.get("cohort_rows") != 120:
        errors.append("stage7-cohort")
    if stage.get("policy_unsafe_overpromotions") != 0:
        errors.append("stage7-unsafe")
    if stage.get("policy_missed_supported") != 0:
        errors.append("stage7-missed-supported")
    if stage.get("python_node_agreement") is not True:
        errors.append("stage7-cross-language")
    if stage.get("tamper_controls_rejected") is not True:
        errors.append("stage7-tamper")
    required_hashes = (
        "artifact_sha256",
        "python_receipt_sha256",
        "node_receipt_sha256",
        "compact_rows_sha256",
        "labels_sha256",
        "candidate_ids_sha256",
    )
    for field in required_hashes:
        value_field = stage.get(field)
        if not isinstance(value_field, str) or len(value_field) != 64:
            errors.append(f"stage7-{field}")
    return errors


def verify_prior_art(contract: Mapping[str, Any], root: Path) -> list[str]:
    errors: list[str] = []
    boundary = _mapping(contract.get("prior_art_boundary"))
    if boundary is None:
        return ["prior-art-boundary"]
    if set(boundary.get("absorbed_components", ())) != REQUIRED_ABSORBED:
        errors.append("prior-art-absorbed")
    if boundary.get("interpretation") != (
        "No exact hit in searched corpora is not proof of global novelty."
    ):
        errors.append("prior-art-interpretation")
    relative = boundary.get("closure_file")
    if not isinstance(relative, str):
        return errors + ["prior-art-file"]
    path = root / relative
    if not path.exists():
        return errors + ["prior-art-file-missing"]
    closure = json.loads(path.read_text(encoding="utf-8"))
    if closure.get("schema") != PRIOR_ART_SCHEMA:
        errors.append("prior-art-schema")
    if closure.get("claim_id") != contract.get("claim_id"):
        errors.append("prior-art-claim-id")
    if closure.get("status") != boundary.get("searched_status"):
        errors.append("prior-art-status")
    if closure.get("cut_date") != boundary.get("search_cut"):
        errors.append("prior-art-cut")
    interpretation = str(closure.get("interpretation", ""))
    if "not proof of global novelty" not in interpretation:
        errors.append("prior-art-caution")
    sources = closure.get("absorbed_primary_prior_art")
    if not isinstance(sources, list) or len(sources) < 10:
        errors.append("prior-art-primary-sources")
    searched = closure.get("searched_corpora")
    if not isinstance(searched, list) or len(searched) < 4:
        errors.append("prior-art-corpora")
    if closure.get("bounded_remaining_claim") != contract.get("claim"):
        errors.append("prior-art-claim-boundary")
    exact_hit = closure.get("exact_claim_match_found")
    if exact_hit not in {None, False}:
        errors.append("prior-art-exact-hit")
    return errors


def verify(contract: Mapping[str, Any], root: Path | None = None) -> list[str]:
    root = root or Path(".")
    errors: list[str] = []
    if contract.get("schema") != CONTRACT_SCHEMA:
        errors.append("schema")
    if contract.get("claim_id") != CLAIM_ID:
        errors.append("claim-id")
    if contract.get("status") not in {"OPEN", "PASS", "FALSIFIED"}:
        errors.append("status")
    if contract.get("canonical_score_before") != 920:
        errors.append("score-before")
    if contract.get("gate_points") != 80:
        errors.append("gate-points")
    claim = str(contract.get("claim", ""))
    if any(phrase not in claim for phrase in REQUIRED_CLAIM_PHRASES):
        errors.append("claim-specificity")
    forbidden_claim_phrases = (
        "proves fraud",
        "proves corruption",
        "universal",
        "first ever entity resolution",
        "first procurement knowledge graph",
    )
    if any(phrase.lower() in claim.lower() for phrase in forbidden_claim_phrases):
        errors.append("claim-expansion")

    scope = _mapping(contract.get("scope"))
    if scope is None:
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
    if contract.get("challenger") != "FIN-RVI-002-DOCUMENTARY-V3":
        errors.append("challenger")
    predictions = contract.get("exclusive_predictions")
    falsifiers = contract.get("falsifiers")
    if not isinstance(predictions, list) or len(predictions) < 6 or len(
        set(predictions)
    ) != len(predictions):
        errors.append("predictions")
    if not isinstance(falsifiers, list) or len(falsifiers) < 7 or len(
        set(falsifiers)
    ) != len(falsifiers):
        errors.append("falsifiers")

    gates = _mapping(contract.get("required_gates"))
    if gates is None or set(gates) != REQUIRED_GATES:
        errors.append("required-gates")
        gates = {}
    elif any(value not in ALLOWED_GATE_VALUES for value in gates.values()):
        errors.append("gate-values")
    for name in (
        "g07_operational_utility",
        "stage4_independent_code_disjoint_cohort",
        "stage5_clean_reconstruction",
        "systematic_primary_prior_art_closure",
        "claim_scope_audit",
    ):
        if gates.get(name) != "PASS":
            errors.append(f"gate-{name}")

    evidence = _mapping(contract.get("empirical_evidence"))
    if evidence is None:
        errors.append("empirical-evidence")
        evidence = {}
    errors.extend(_verify_stage4(evidence.get("stage4")))
    errors.extend(_verify_stage5(evidence.get("stage5")))
    final_required = contract.get("status") == "PASS"
    errors.extend(_verify_stage6(evidence.get("stage6"), final_required))
    errors.extend(_verify_stage7(evidence.get("stage7"), final_required))
    errors.extend(verify_prior_art(contract, root))

    readout = _mapping(contract.get("gate_readout"))
    if readout is None:
        errors.append("gate-readout")
    else:
        if readout.get("G07") != "PASS":
            errors.append("readout-g07")
        if contract.get("status") == "PASS":
            if any(gates.get(name) != "PASS" for name in REQUIRED_GATES):
                errors.append("premature-pass")
            if readout != {"G07": "PASS", "G09": "PASS", "finance_score": 1000}:
                errors.append("pass-readout")
        elif contract.get("status") == "OPEN":
            if all(gates.get(name) == "PASS" for name in REQUIRED_GATES):
                errors.append("stale-open")
            if readout.get("G09") == "PASS" or readout.get("finance_score") != 920:
                errors.append("premature-score")
        elif contract.get("status") == "FALSIFIED":
            if readout.get("G09") == "PASS" or readout.get("finance_score") != 920:
                errors.append("falsified-score")
    return sorted(set(errors))


def build_receipt(contract: Mapping[str, Any], root: Path | None = None) -> dict[str, Any]:
    errors = verify(contract, root)
    gates = _mapping(contract.get("required_gates")) or {}
    passed = sum(value == "PASS" for value in gates.values())
    promotion = (
        not errors
        and contract.get("status") == "PASS"
        and passed == len(REQUIRED_GATES)
    )
    payload = {
        "schema": "fin-rvi-002/g09-final-contract-receipt/2",
        "claim_id": contract.get("claim_id"),
        "contract_sha256": digest(contract),
        "valid": not errors,
        "errors": errors,
        "status": contract.get("status"),
        "passed_required_gates": passed,
        "total_required_gates": len(REQUIRED_GATES),
        "promotion_allowed": promotion,
        "gate_readout": (
            {"G07": "PASS", "G09": "PASS", "finance_score": 1000}
            if promotion
            else {
                "G07": "PASS",
                "G09": "OPEN",
                "finance_score": 920,
            }
        ),
    }
    return {"payload": payload, "sha256": digest(payload)}


def main() -> int:
    source = Path("fin_rvi_002_g09/final_contract_v2.json")
    contract = json.loads(source.read_text(encoding="utf-8"))
    receipt = build_receipt(contract, Path("."))
    output = Path("reports/fin_rvi_002_g09_v2")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "final_contract_receipt.json"
    target.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["payload"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
