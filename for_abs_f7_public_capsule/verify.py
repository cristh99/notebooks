"""Independent public verifier for FOR-ABS-001 F7 receipts.

This capsule does not import the private implementation. It independently checks
receipt digests, source/amount manifests, chronology, arithmetic, executed negative
attacks, cross-file lineage, frozen-rule promotion and epistemic guardrails.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
FILES = {
    "bundle": ROOT / "receipts" / "case-bundle.json",
    "replay": ROOT / "receipts" / "adversarial-replay-v2.json",
    "pointer": ROOT / "receipts" / "operational-pointer-v2.json",
    "promotion": ROOT / "receipts" / "promotion-v2.json",
}
SOURCE_TYPES = {
    "recordOpeningTendersReceived",
    "awardNotice",
    "contractSigned",
    "structuredRelease",
}
DOCUMENT_TYPES = SOURCE_TYPES - {"structuredRelease"}
BLOCKS = {
    "F7A_SOURCE_BOUND_DOCUMENT_SET",
    "F7B_AMOUNT_ROLE_AND_CHRONOLOGY",
    "F7C_REPRODUCIBLE_CASE_BUNDLE",
    "F7D_INDEPENDENT_ADVERSARIAL_REPLAY",
}
REPLAY_FLAGS = {
    "ocr_perturbation_pass",
    "all_correct_observations_accepted",
    "chronology_exact",
    "source_hash_tamper_rejected",
    "page_substitution_rejected",
    "role_swap_rejected",
    "document_substitution_rejected",
}
EXPECTED_AMOUNTS = {
    "OFFER": (2960881999, "recordOpeningTendersReceived", 1),
    "OFFER_RECORDED_IN_AWARD": (2960881999, "awardNotice", 2),
    "NEGOTIATED_OFFER": (2950000000, "awardNotice", 2),
    "CONTRACT_AMOUNT": (1744546486, "contractSigned", 1),
    "PERFORMANCE_GUARANTEE_15_PERCENT": (261681973, "contractSigned", 2),
    "STRUCTURED_CONTRACT_VALUE": (174454648600, "structuredRelease", None),
}
EXPECTED_CHRONOLOGY = (
    "recordOpeningTendersReceived",
    "awardNotice",
    "contractSigned",
)


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    raw = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(value: Any, name: str) -> str:
    text = str(value or "")
    require(len(text) == 64 and all(char in "0123456789abcdef" for char in text), f"invalid SHA-256: {name}")
    return text


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_embedded(payload: Mapping[str, Any], field: str) -> str:
    expected = sha(payload.get(field), field)
    body = dict(payload)
    body.pop(field, None)
    require(digest(body) == expected, f"digest mismatch: {field}")
    return expected


def source_map(rows: Any, *, type_key: str, hash_key: str) -> dict[str, Mapping[str, Any]]:
    require(isinstance(rows, list) and len(rows) == 4, "source manifest size")
    result: dict[str, Mapping[str, Any]] = {}
    hashes: set[str] = set()
    for row in rows:
        require(isinstance(row, Mapping), "source row type")
        kind = str(row.get(type_key) or "")
        require(kind not in result, "duplicate source type")
        result[kind] = row
        source_hash = sha(row.get(hash_key), f"source:{kind}")
        require(source_hash not in hashes, "duplicate source hash")
        hashes.add(source_hash)
        locator = row.get("source_locator_commitment_sha256")
        if locator is not None:
            sha(locator, f"locator:{kind}")
        if kind in DOCUMENT_TYPES:
            require(int(row.get("pages", row.get("page_count", 0))) > 0, "invalid page count")
        if kind == "structuredRelease":
            sha(row.get("release_sha256"), "structured release")
    require(set(result) == SOURCE_TYPES, "source type set")
    return result


def verify_bundle(bundle: Mapping[str, Any]) -> str:
    receipt = verify_embedded(bundle, "receipt_sha256")
    require(bundle.get("schema_version") == "hn_for_abs_001_f7_case_bundle/v1", "bundle schema")
    require(bundle.get("status") == "F7_CASE_BUNDLE_RECONSTRUCTED_FAIL_CLOSED", "bundle status")
    require(bundle.get("test_holdout_open_count") == 0, "bundle holdout")
    require(bundle.get("corruption_claims_created") == 0, "bundle corruption claim")
    require(bundle.get("illegality_claims_created") == 0, "bundle illegality claim")
    for field in (
        "clean_or_negative_state_created",
        "amount_disagreement_proves_corruption",
        "stage_substitution_allowed",
        "raw_source_locators_exported",
        "raw_actor_names_exported",
        "raw_hypothesis_text_exported",
    ):
        require(bundle.get(field) is False, f"bundle guard: {field}")
    sha(bundle.get("case_commitment_sha256"), "case commitment")
    sha(bundle.get("builder_module_sha256"), "builder module")
    sha(bundle.get("builder_test_receipt_sha256"), "builder test")
    sha(bundle.get("independent_replay_receipt_sha256"), "replay v1")
    sources = source_map(bundle.get("source_manifest"), type_key="document_type", hash_key="source_sha256")
    require(int(bundle.get("source_count", 0)) == 4, "bundle source count")
    require(int(bundle.get("source_type_count", 0)) == 4, "bundle source-type count")

    amounts = bundle.get("amount_manifest")
    require(isinstance(amounts, list) and len(amounts) == 6, "bundle amount count")
    require(int(bundle.get("amount_observation_count", 0)) == 6, "bundle amount denominator")
    by_role: dict[str, Mapping[str, Any]] = {}
    for row in amounts:
        require(isinstance(row, Mapping), "amount row type")
        role = str(row.get("role") or "")
        require(role not in by_role, "duplicate amount role")
        by_role[role] = row
        sha(row.get("observation_commitment_sha256"), f"amount commitment:{role}")
        require(row.get("currency") == "HNL", "amount currency")
    require(set(by_role) == set(EXPECTED_AMOUNTS), "amount role set")
    for role, (amount, source_type, page) in EXPECTED_AMOUNTS.items():
        row = by_role[role]
        require(int(row.get("amount_cents", -1)) == amount, f"amount value:{role}")
        require(row.get("source_type") == source_type, f"amount source:{role}")
        if page is not None:
            require(int(row.get("source_page", 0)) == page, f"amount page:{role}")
        else:
            require(row.get("source_path") == "contracts[0].value", "structured source path")

    arithmetic = bundle.get("arithmetic")
    require(isinstance(arithmetic, Mapping), "bundle arithmetic")
    offer = Decimal(EXPECTED_AMOUNTS["OFFER"][0])
    negotiated = Decimal(EXPECTED_AMOUNTS["NEGOTIATED_OFFER"][0])
    contract = Decimal(EXPECTED_AMOUNTS["CONTRACT_AMOUNT"][0])
    guarantee = Decimal(EXPECTED_AMOUNTS["PERFORMANCE_GUARANTEE_15_PERCENT"][0])
    structured = Decimal(EXPECTED_AMOUNTS["STRUCTURED_CONTRACT_VALUE"][0])
    require(structured == contract * 100, "bundle 100x arithmetic")
    require(guarantee == (contract * Decimal("0.15")).quantize(Decimal("1"), rounding=ROUND_HALF_UP), "bundle 15% arithmetic")
    require(Decimal(str(arithmetic.get("offer_to_negotiated_delta_cents"))) == offer - negotiated, "bundle offer delta")
    require(Decimal(str(arithmetic.get("negotiated_to_contract_delta_cents"))) == negotiated - contract, "bundle contract delta")
    require(arithmetic.get("structured_exactly_100x_contract") is True, "bundle 100x flag")
    require(arithmetic.get("guarantee_rounds_to_15_percent_contract") is True, "bundle 15% flag")
    require(Decimal(str(arithmetic.get("structured_to_contract_ratio"))) == 100, "bundle ratio")

    chronology = bundle.get("chronology")
    require(isinstance(chronology, list) and len(chronology) == 3, "chronology size")
    types: list[str] = []
    dates: list[datetime] = []
    for row in chronology:
        require(isinstance(row, Mapping), "chronology row")
        types.append(str(row.get("document_type") or ""))
        published = str(row.get("published_at") or "")
        dates.append(datetime.fromisoformat(published))
        require(digest(published) == row.get("published_at_commitment_sha256"), "chronology commitment")
    require(tuple(types) == EXPECTED_CHRONOLOGY, "chronology order")
    require(dates == sorted(dates), "chronology dates")
    require(bundle.get("chronology_exact") is True, "chronology flag")

    claims = bundle.get("claim_evidence_matrix")
    hypotheses = bundle.get("hypothesis_manifest")
    require(isinstance(claims, list) and len(claims) >= 5, "claim matrix")
    require(isinstance(hypotheses, list) and len(hypotheses) >= 5, "hypothesis matrix")
    require(int(bundle.get("rival_hypothesis_count", 0)) == len(hypotheses), "hypothesis denominator")
    require(any(row.get("disposition") == "NOT_EVALUABLE" for row in claims), "claim boundary")
    statuses = {str(row.get("status") or "") for row in hypotheses}
    require({"SUPPORTED_OBSERVATION", "UNRESOLVED", "CONTRADICTED", "NOT_EVALUABLE"}.issubset(statuses), "hypothesis statuses")
    for row in claims:
        sha(row.get("claim_commitment_sha256"), "claim commitment")
        sha(row.get("evidence_manifest_sha256"), "claim evidence")
        require(int(row.get("evidence_count", 0)) > 0, "claim evidence denominator")
    for row in hypotheses:
        for field in (
            "hypothesis_commitment_sha256",
            "statement_commitment_sha256",
            "evidence_for_manifest_sha256",
            "evidence_against_manifest_sha256",
            "missing_evidence_manifest_sha256",
        ):
            sha(row.get(field), f"hypothesis:{field}")
        require(int(row.get("evidence_for_count", 0)) > 0, "hypothesis support")
        require(int(row.get("evidence_against_count", 0)) > 0, "hypothesis counter")
        require(int(row.get("missing_evidence_count", 0)) > 0, "hypothesis missing")
    return receipt


def verify_replay(replay: Mapping[str, Any]) -> str:
    receipt = verify_embedded(replay, "receipt_sha256")
    require(replay.get("schema_version") == "hn_for_abs_001_f7_independent_adversarial_replay/v2", "replay schema")
    require(replay.get("status") == "F7_INDEPENDENT_ADVERSARIAL_REPLAY_V2_PASS", "replay status")
    require(replay.get("test_holdout_open_count") == 0, "replay holdout")
    require(replay.get("corruption_claims_created") == 0, "replay corruption claim")
    require(replay.get("raw_text_exported") is False, "replay raw text")
    require(replay.get("raw_source_locators_exported") is False, "replay raw locators")
    require(Decimal(str(replay.get("external_ocr_spend_usd"))) == 0, "replay spend")
    sha(replay.get("supersedes_receipt_sha256"), "replay supersedes")
    sha(replay.get("document_canary_receipt_sha256"), "replay canary")
    for field in REPLAY_FLAGS:
        require(replay.get(field) is True, f"replay flag:{field}")
    expected = int(replay.get("expected_observation_count", 0))
    require(expected == 5, "replay observation denominator")
    require(int(replay.get("correct_observation_acceptance_count", 0)) == expected, "replay correct acceptances")
    for count_field, digest_field in (
        ("page_substitution_attack_count", "page_substitution_attack_manifest_sha256"),
        ("role_swap_attack_count", "role_swap_attack_manifest_sha256"),
        ("document_substitution_attack_count", "document_substitution_attack_manifest_sha256"),
    ):
        require(int(replay.get(count_field, 0)) == expected, f"replay attack count:{count_field}")
        sha(replay.get(digest_field), f"replay attack manifest:{digest_field}")
    ocr = replay.get("ocr_perturbation_results")
    require(isinstance(ocr, list) and len(ocr) == expected, "replay OCR denominator")
    commitments: set[str] = set()
    for row in ocr:
        commitment = sha(row.get("observation_commitment_sha256"), "OCR observation")
        require(commitment not in commitments, "duplicate OCR observation")
        commitments.add(commitment)
        require(row.get("psm6_present") is True and row.get("psm11_present") is True, "OCR mode parity")
        require(row.get("ocr_perturbation_pass") is True, "OCR perturbation")
    sources = replay.get("source_results")
    require(isinstance(sources, list) and len(sources) == 3, "replay source denominator")
    types: set[str] = set()
    hashes: set[str] = set()
    for row in sources:
        types.add(str(row.get("document_type") or ""))
        source_hash = sha(row.get("source_sha256"), "replay source")
        require(source_hash not in hashes, "duplicate replay source hash")
        hashes.add(source_hash)
        sha(row.get("tampered_source_sha256"), "tampered source")
        require(row.get("source_hash_match") is True, "source hash mismatch")
        require(row.get("tampered_source_rejected") is True, "tampered source accepted")
        fetch = row.get("fetch")
        require(isinstance(fetch, Mapping), "fetch metadata")
        require(int(fetch.get("http_status", 0)) == 200, "fetch status")
        require(fetch.get("source_hash_match") is True, "fetch hash")
        sha(fetch.get("content_type_commitment_sha256"), "content type commitment")
    require(types == DOCUMENT_TYPES, "replay source types")
    return receipt


def verify_pointer(pointer: Mapping[str, Any], bundle: Mapping[str, Any], replay: Mapping[str, Any]) -> str:
    receipt = verify_embedded(pointer, "pointer_receipt_sha256")
    require(pointer.get("schema_version") == "hn_for_abs_001_f7_case_bundle_pointer/v2", "pointer schema")
    require(pointer.get("status") == "F7_CASE_BUNDLE_RECONSTRUCTED_FAIL_CLOSED", "pointer status")
    require(pointer.get("test_holdout_open_count") == 0, "pointer holdout")
    require(pointer.get("corruption_claims_created") == 0, "pointer corruption claim")
    require(pointer.get("illegality_claims_created") == 0, "pointer illegality claim")
    require(pointer.get("clean_or_negative_state_created") is False, "pointer clean state")
    require(pointer.get("raw_source_locators_exported") is False, "pointer raw locators")
    require(pointer.get("operational_receipt_sha256") == bundle.get("receipt_sha256"), "pointer bundle lineage")
    require(pointer.get("independent_replay_receipt_sha256") == replay.get("receipt_sha256"), "pointer replay lineage")
    require(pointer.get("superseded_replay_v1_receipt_sha256") == replay.get("supersedes_receipt_sha256"), "pointer replay supersession")
    require(pointer.get("case_commitment_sha256") == bundle.get("case_commitment_sha256"), "pointer case commitment")
    require(pointer.get("builder_module_sha256") == bundle.get("builder_module_sha256"), "pointer builder")
    require(pointer.get("builder_test_receipt_sha256") == bundle.get("builder_test_receipt_sha256"), "pointer builder test")
    require(pointer.get("promotion_rule_commit") == bundle.get("promotion_rule_commit"), "pointer rule")
    pointer_sources = source_map(pointer.get("sources"), type_key="type", hash_key="sha256")
    bundle_sources = source_map(bundle.get("source_manifest"), type_key="document_type", hash_key="source_sha256")
    for kind in SOURCE_TYPES:
        require(pointer_sources[kind].get("sha256") == bundle_sources[kind].get("source_sha256"), f"pointer source:{kind}")
    amounts = pointer.get("amounts_hnl")
    arithmetic = pointer.get("arithmetic")
    require(isinstance(amounts, Mapping) and isinstance(arithmetic, Mapping), "pointer amounts")
    offer = Decimal(str(amounts["offer"]))
    negotiated = Decimal(str(amounts["negotiated_offer"]))
    contract = Decimal(str(amounts["signed_contract"]))
    guarantee = Decimal(str(amounts["performance_guarantee"]))
    structured = Decimal(str(amounts["structured_contract_value"]))
    require(structured == contract * 100, "pointer 100x")
    require(guarantee == (contract * Decimal("0.15")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "pointer guarantee")
    require(Decimal(str(arithmetic["offer_to_negotiated_delta_hnl"])) == offer - negotiated, "pointer offer delta")
    require(Decimal(str(arithmetic["negotiated_to_contract_delta_hnl"])) == negotiated - contract, "pointer contract delta")
    bundle_values = {row["role"]: Decimal(str(row["amount_cents"])) / 100 for row in bundle["amount_manifest"]}
    for role, value in {
        "OFFER": offer,
        "NEGOTIATED_OFFER": negotiated,
        "CONTRACT_AMOUNT": contract,
        "PERFORMANCE_GUARANTEE_15_PERCENT": guarantee,
        "STRUCTURED_CONTRACT_VALUE": structured,
    }.items():
        require(bundle_values.get(role) == value, f"pointer amount lineage:{role}")
    summary = pointer.get("independent_replay")
    require(isinstance(summary, Mapping), "pointer replay summary")
    for field in REPLAY_FLAGS:
        require(summary.get(field) is True and replay.get(field) is True, f"pointer replay flag:{field}")
    for field in (
        "expected_observation_count",
        "correct_observation_acceptance_count",
        "page_substitution_attack_count",
        "role_swap_attack_count",
        "document_substitution_attack_count",
    ):
        require(int(summary.get(field, -1)) == int(replay.get(field, -2)), f"pointer replay count:{field}")
    return receipt


def verify_promotion(promotion: Mapping[str, Any], pointer: Mapping[str, Any], bundle: Mapping[str, Any], replay: Mapping[str, Any]) -> str:
    receipt = verify_embedded(promotion, "receipt_sha256")
    require(promotion.get("schema_version") == "hn_for_abs_001_f7_promotion_audit/v2", "promotion schema")
    require(promotion.get("status") == "PASS_F7_PROMOTION_AUDIT_V2", "promotion status")
    require(promotion.get("test_holdout_open_count") == 0, "promotion holdout")
    require(promotion.get("corruption_claims_created") == 0, "promotion corruption claim")
    blocks = promotion.get("blocks")
    require(isinstance(blocks, Mapping) and set(blocks) == BLOCKS, "promotion blocks")
    require(all(blocks.get(block) is True for block in BLOCKS), "promotion failed block")
    expected = {
        "passed_blocks": 4,
        "baseline_f7": 66,
        "f7_after": 82,
        "f7_change": 16,
        "baseline_total": 655,
        "total_after": 671,
        "total_change": 16,
        "f7_cap": 82,
    }
    for field, value in expected.items():
        require(int(promotion.get(field, -1)) == value, f"promotion number:{field}")
    require(promotion.get("is_god_mode") is False, "promotion God Mode")
    require(promotion.get("case_bundle_receipt_sha256") == bundle.get("receipt_sha256"), "promotion bundle lineage")
    require(promotion.get("adversarial_replay_v2_receipt_sha256") == replay.get("receipt_sha256"), "promotion replay lineage")
    require(promotion.get("superseded_replay_v1_receipt_sha256") == replay.get("supersedes_receipt_sha256"), "promotion supersession")
    require(promotion.get("receipt_sha256") == pointer.get("promotion_v2_receipt_sha256"), "promotion pointer")
    require(promotion.get("rule_commit") == pointer.get("promotion_rule_commit"), "promotion rule")
    require(set(promotion.get("remaining_noncompensable_gates") or []) == {"F2", "F6", "F8", "F9"}, "promotion blockers")
    return receipt


def verify_all(payloads: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    data = dict(payloads or {name: load(path) for name, path in FILES.items()})
    bundle_receipt = verify_bundle(data["bundle"])
    replay_receipt = verify_replay(data["replay"])
    pointer_receipt = verify_pointer(data["pointer"], data["bundle"], data["replay"])
    promotion_receipt = verify_promotion(data["promotion"], data["pointer"], data["bundle"], data["replay"])
    report = {
        "schema_version": "for_abs_f7_public_verification/v1",
        "status": "PASS",
        "score_before": 655,
        "score_after": 671,
        "f7_before": 66,
        "f7_after": 82,
        "minimum_gate": 38,
        "is_god_mode": False,
        "case_bundle_receipt_sha256": bundle_receipt,
        "adversarial_replay_v2_receipt_sha256": replay_receipt,
        "pointer_receipt_sha256": pointer_receipt,
        "promotion_receipt_sha256": promotion_receipt,
        "executed_negative_attacks": 18,
        "holdout_open_count": 0,
        "corruption_claims_created": 0,
        "network_calls": 0,
        "external_spend_usd": 0,
        "boundary": "This finite public verification proves receipt integrity, arithmetic, lineage and declared adversarial controls. It does not establish payment, acceptance, corruption, utility, generalization or God Mode.",
    }
    report["report_digest"] = digest(report)
    return report


def main() -> None:
    report = verify_all()
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
