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
    "procurement_payment_red_flags",
    "audit_document_sufficiency_and_three_way_matching",
    "purchase_order_invoice_vendor_reconciliation",
    "many_to_many_purchase_to_pay_process_modeling",
    "open_set_document_rejection",
    "contract_payment_reconciliation_patents",
    "Honduras_procurement_financial_system_integration",
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
EXPECTED_STAGE3 = {
    "run_id": 30840335568,
    "artifact_id": 8866730681,
    "artifact_sha256": "96da8227f2c9ab0f597acbb9286fe1cfa67f1b08bc344d6239297555a258fa95",
    "report_sha256": "e12ac82c517ede58cbe2ee1339c24ae6c406251c08e562afd856e65eb859c6f4",
}
EXPECTED_STAGE4 = {
    "head": "9e6686204fce20bc21d17f041d506a2a9c92761d",
    "run_id": 30841561243,
    "artifact_id": 8867231467,
    "artifact_sha256": "a1a4a2e7dd3a722ce9b1dac9b5dbe02a5bfde0f7bd63c9e5fb6974c056de3928",
    "report_sha256": "83e83d5893c7df8ab425debbb21e9edd5eda60e08309cfbd4905bd84a5ffbc7d",
}
EXPECTED_STAGE5 = {
    "head": "d9928f064d0ff80084d46c9fae73d7717dffbfbd",
    "run_id": 30844453922,
    "artifact_id": 8868335548,
    "artifact_sha256": "53920001230a0ea13f3929f0abcdf529653759a8e869dd1707499029ba867462",
    "reconstructed_report_sha256": "e825184bc0e4389e8475b9a861d852b40c39b57322cbad574b4d4880fc67f811",
    "python_receipt_sha256": "03e97d0eb13ad7808a1a78f37ff2e8d16695ca092ccf3ed76f7cd12a78b795be",
    "node_receipt_sha256": "3fa82f11d111d97e3b5fcaf58680a413f1482e01744e336cd5e64fa0c33d72d6",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _contains_expected(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def verify(contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema") != "fin-rvi-002/g09-claim-contract/2":
        errors.append("schema")
    if contract.get("claim_id") != "FIN-RVI-002-C1":
        errors.append("claim-id")
    status = contract.get("status")
    if status not in {"OPEN", "PASS", "FALSIFIED", "UNDERSPECIFIED"}:
        errors.append("status")

    claim = str(contract.get("claim", ""))
    required_phrases = (
        "sealed public ONCAE-SEFIN holdout",
        "120 pairs",
        "exact contract/project-code blocking",
        "compatible supplier identity",
        "strictly reduces unsupported promotions",
        "from 20 to 0",
        "without reducing supported-payment recovery",
        "58/58 under both",
        "one-to-many contract-financial-event cardinality",
        "fail-closed abstention",
        "clean reconstruction reproduces",
    )
    if any(phrase not in claim for phrase in required_phrases):
        errors.append("claim-specificity")

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
        if not scope.get("external_validity"):
            errors.append("external-validity")

    novelty = _mapping(contract.get("novelty_classification"))
    if novelty is None:
        errors.append("novelty-classification")
    else:
        if novelty.get("type") != "DOMAIN_BOUNDED_ORIGINAL_EMPIRICAL_RESULT":
            errors.append("novelty-type")
        if novelty.get("broad_method_novelty") is not False:
            errors.append("broad-method-novelty")
        if novelty.get("exact_claim_match_found_in_bounded_search") is not False:
            errors.append("prior-art-exact-match")
        if novelty.get("revocable_if_prior_art_found") is not True:
            errors.append("novelty-revocability")

    if contract.get("strong_baseline") != "B1_CODE_SUPPLIER":
        errors.append("strong-baseline")
    if contract.get("challenger") != "POLICY_DOCUMENTARY_V3":
        errors.append("challenger")
    if not REQUIRED_ABSORBED.issubset(set(contract.get("prior_art_absorbed", ()))):
        errors.append("prior-art-boundary")

    required = _mapping(contract.get("required_gates"))
    current = _mapping(contract.get("current_gates"))
    if required is None or set(required) != REQUIRED_GATES:
        errors.append("required-gates")
    elif any(value != "PASS" for value in required.values()):
        errors.append("gate-contract")
    if current is None or set(current) != REQUIRED_GATES:
        errors.append("current-gates")
    if status == "PASS":
        if current is None or any(current.get(gate) != "PASS" for gate in REQUIRED_GATES):
            errors.append("premature-pass")
    if status == "OPEN" and current is not None and all(
        current.get(gate) == "PASS" for gate in REQUIRED_GATES
    ):
        errors.append("stale-open")

    evidence = _mapping(contract.get("empirical_evidence"))
    if evidence is None:
        errors.append("empirical-evidence")
    else:
        stage3 = _mapping(evidence.get("development_stage3"))
        stage4 = _mapping(evidence.get("independent_stage4"))
        stage5 = _mapping(evidence.get("clean_stage5"))
        if stage3 is None or not _contains_expected(stage3, EXPECTED_STAGE3):
            errors.append("stage3-lineage")
        elif (
            stage3.get("cohort_size") != 120
            or stage3.get("labels") != {"SUPPORTED": 57, "REJECTED": 34, "UNRESOLVED": 29}
            or stage3.get("baseline") != {"unsafe_overpromotions": 19, "supported_recovered": 57}
            or stage3.get("challenger_v2") != {"unsafe_overpromotions": 17, "supported_recovered": 56}
            or stage3.get("role") != "COUNTEREXAMPLE_GUIDED_DEVELOPMENT_ONLY"
        ):
            errors.append("stage3-result")
        if stage4 is None or not _contains_expected(stage4, EXPECTED_STAGE4):
            errors.append("stage4-lineage")
        elif (
            stage4.get("cohort_size") != 120
            or stage4.get("stage3_shared_codes_excluded") != 118
            or stage4.get("labels") != {"SUPPORTED": 58, "REJECTED": 28, "UNRESOLVED": 34}
            or stage4.get("baseline") != {
                "promotions": 78,
                "unsafe_overpromotions": 20,
                "supported_recovered": 58,
                "missed_supported": 0,
            }
            or stage4.get("challenger_v3") != {
                "promotions": 58,
                "unsafe_overpromotions": 0,
                "supported_recovered": 58,
                "missed_supported": 0,
            }
            or stage4.get("permutation") != {
                "promotions": 58,
                "unsafe_overpromotions": 21,
                "supported_recovered": 37,
            }
            or stage4.get("unsupported_amount_at_risk_avoided_hnl") != 39048528.39
            or stage4.get("all_preregistered_checks") is not True
        ):
            errors.append("stage4-result")
        if stage5 is None or not _contains_expected(stage5, EXPECTED_STAGE5):
            errors.append("stage5-lineage")
        elif (
            stage5.get("all_python_gates") is not True
            or stage5.get("all_node_gates") is not True
            or stage5.get("finance_score_after_g07") != 920
        ):
            errors.append("stage5-result")

    prior = _mapping(contract.get("prior_art_search"))
    if prior is None:
        errors.append("prior-art-search")
    elif (
        prior.get("log_path")
        != "fin_rvi_002_g09/prior_art_search_log_20260803.json"
        or prior.get("status") != "PASS_BOUNDED_MULTI_INDEX_SEARCH"
        or prior.get("exact_claim_match_found") is not False
        or prior.get("cut_date") != "2026-08-03"
    ):
        errors.append("prior-art-search")

    predictions = contract.get("exclusive_predictions")
    falsifiers = contract.get("falsifiers")
    if not isinstance(predictions, list) or len(predictions) < 6 or len(set(predictions)) != len(predictions):
        errors.append("predictions")
    if not isinstance(falsifiers, list) or len(falsifiers) < 7 or len(set(falsifiers)) != len(falsifiers):
        errors.append("falsifiers")

    sources = contract.get("primary_sources")
    if not isinstance(sources, list) or len(sources) < 20:
        errors.append("primary-sources")
    else:
        kinds = {source.get("kind") for source in sources if isinstance(source, Mapping)}
        if not {"scholarly", "official_standard", "official_project", "official_report", "patent"}.issubset(kinds):
            errors.append("source-diversity")
        if any(
            not isinstance(source, Mapping)
            or not source.get("title")
            or not source.get("absorbs")
            or not any(source.get(key) for key in ("doi", "identifier", "url", "venue", "publisher"))
            for source in sources
        ):
            errors.append("primary-source-shape")
    return errors


def build_receipt(contract: Mapping[str, Any]) -> dict[str, Any]:
    errors = verify(contract)
    current = contract.get("current_gates", {})
    passed = sum(value == "PASS" for value in current.values()) if isinstance(current, Mapping) else 0
    promotion = (
        not errors
        and contract.get("status") == "PASS"
        and passed == len(REQUIRED_GATES)
    )
    payload = {
        "schema": "fin-rvi-002/g09-claim-receipt/2",
        "claim_id": contract.get("claim_id"),
        "contract_sha256": digest(contract),
        "valid": not errors,
        "errors": errors,
        "status": contract.get("status"),
        "passed_required_gates": passed,
        "total_required_gates": len(REQUIRED_GATES),
        "promotion_allowed": promotion,
        "gate_readout": {
            "G07": "PASS",
            "G09": "PASS" if promotion else "OPEN",
            "finance_score": 1000 if promotion else 920,
        },
        "boundary": (
            "G09 PASS is a domain-bounded original empirical result under the "
            "declared search cut and cohorts. It does not claim novelty of the "
            "underlying reconciliation, record-linkage, provenance, abstention, "
            "or information-acquisition methods."
        ),
    }
    return {"payload": payload, "sha256": digest(payload)}


def main() -> int:
    source = Path("fin_rvi_002_g09/claim_contract.json")
    contract = json.loads(source.read_text(encoding="utf-8"))
    receipt = build_receipt(contract)
    output = Path("reports/fin_rvi_002_g09")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "claim_receipt.json"
    target.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True, ensure_ascii=False))
    return 0 if receipt["payload"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
