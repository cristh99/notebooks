from __future__ import annotations

import re
from typing import Any

HEX64 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

EXPECTED = [
    ("3d8728b9-99fb-45e5-a78d-3e6d85541be4", 1, "6c43baefc7e9f7a357a958f621f02575a6c98d0011f3ba2999075d43728c7580", 0, True, True),
    ("306cb066-c977-4929-9762-b28654ed8e82", 1, "0353798bb530b096c99a7544040a81667f691d818c0a9663d1a447ada48391b5", 0, True, True),
    ("57893e09-a6a2-4b31-bc05-65bf31f12cf8", 1, "53cf07adc936062c2bd043b62d0033329d071d92d667049386bc41b064e58e5f", 0, True, False),
    ("110090a3-e03b-45fb-bbc1-ae000dcf4018", 1, "e118e573193792b30be58d42ed4439ce223de4ae568234d678eac552cd9486fb", 0, True, True),
    ("9af07943-a7f0-422e-a306-9bdf2f14fd74", 2, "dd9e9135c5f2085f7ee0b0a14bf6394bcc5ed83f9373ab53959f2ffc079b1697", 3, False, True),
    ("0be6dfca-63f6-4f8a-9c37-07be1dc67bff", 2, "13eb146f65ff37e09e442a8dc63299653f1d146bdb2cc6140ffd2c3b3b9c7f11", 3, True, True),
    ("0772e7d9-1613-4547-ac3c-4f8bdd845c1c", 1, "2927e37506fd29cdc2dcf33a6be3d4da4a08126dfa5e6acee324a5f612ceaacf", 20, True, True),
    ("4adb5856-8c47-4a5e-aee3-7ee14171c888", 2, "9c227104e39c9ef720fcd402e9e4b563c7f5555c90027888a3b062f686ead6c3", 0, True, True),
]

SCOPE = [
    "all_rows_read_under_receipt",
    "all_candidates_selected_or_disclosed_under_receipt",
    "all_transitive_derivatives_and_replays",
]


def lineage_is_excluded(
    registry: dict[str, Any],
    *,
    receipt_sha256: str | None = None,
    flight_id: str | None = None,
    run_attempt: int | None = None,
) -> bool:
    if receipt_sha256 is not None:
        return any(entry["receipt_sha256"] == receipt_sha256 for entry in registry["entries"])
    if flight_id is not None and run_attempt is not None:
        return any(
            entry["flight_id"] == flight_id and entry["run_attempt"] == run_attempt
            for entry in registry["entries"]
        )
    raise ValueError("missing provenance fails closed")


def validate_registry(registry: dict[str, Any]) -> dict[str, bool]:
    entries = registry["entries"]
    observed = sorted(
        (
            entry["flight_id"],
            entry["run_attempt"],
            entry["receipt_sha256"],
            entry["selected_candidate_count_disclosed"],
            entry["outcome_accessed"],
            entry["identity_accessed"],
        )
        for entry in entries
    )
    expected = sorted(EXPECTED)
    receipts = [entry["receipt_sha256"] for entry in entries]
    flights = [(entry["flight_id"], entry["run_attempt"]) for entry in entries]
    authority = registry["authority"]
    governance = registry["governance"]
    randomness = registry["future_randomness"]
    policy = registry["exclusion_policy"]
    checks = {
        "schema_exact": registry["schema"] == "data-science-pipeline/stage09-contamination-exclusion-registry/1",
        "coordination_exact": registry["coordination_id"] == "COORD-2026-08-06-PARALLEL-V2",
        "stage_exact": registry["stage"] == "09 — Analyze",
        "status_exact": registry["registry_status"] == "FROZEN_BEFORE_FUTURE_RANDOMNESS",
        "canonical_pr_exact": authority["canonical_stage09_pr"] == 153,
        "canonical_head_exact": authority["canonical_stage09_head"] == "499ff89d5c2b8a97b70f1d871d64345875192f98",
        "recovery_pr_exact": authority["recovery_protocol_pr"] == 161,
        "recovery_head_exact": authority["recovery_protocol_head"] == "9eba1bdec80dc9fedd763bb1d0afc9637203c3b4",
        "recovery_hash_exact": authority["recovery_protocol_sha256"] == "c206d9a93792cc015171ee4266d29d133c042de975f7010169259edce8e0911c",
        "recovery_self_hash_exact": authority["recovery_protocol_self_hash"] == "8a190fb642129357f105ca05e6727aab78fd7425a49427585d784c1ca6582560",
        "ledger_hash_exact": authority["contamination_ledger_sha256"] == "99d950e6395c32b1fef6e3e428988e3b9ab23be01fd911c41d4fa2106ec04971",
        "ledger_self_hash_exact": authority["contamination_ledger_self_hash"] == "402f0cd5edc5d6c67e1fdbac5ff5ed54ee82d15d9821b62e501af5d5927a9fd8",
        "entry_count_exact": len(entries) == 8,
        "entry_set_exact": observed == expected,
        "receipt_hashes_valid": all(HEX64.fullmatch(value) for value in receipts),
        "receipt_hashes_unique": len(receipts) == len(set(receipts)),
        "flight_keys_valid": all(UUID.fullmatch(flight) and attempt >= 1 for flight, attempt in flights),
        "flight_keys_unique": len(flights) == len(set(flights)),
        "selected_count_exact": sum(entry["selected_candidate_count_disclosed"] for entry in entries) == 26,
        "selected_counts_nonnegative": all(entry["selected_candidate_count_disclosed"] >= 0 for entry in entries),
        "outcome_count_exact": sum(bool(entry["outcome_accessed"]) for entry in entries) == 7,
        "identity_count_exact": sum(bool(entry["identity_accessed"]) for entry in entries) == 7,
        "commitments_unavailable": all(entry["candidate_commitments_available"] is False for entry in entries),
        "scope_exact": all(entry["exclusion_scope"] == SCOPE for entry in entries),
        "aggregate_exact": registry["aggregate"] == {
            "receipt_count": 8,
            "disclosed_selected_candidate_count": 26,
            "outcome_accessed_receipt_count": 7,
            "identity_accessed_receipt_count": 7,
            "candidate_commitments_enumerated": 0,
            "candidate_commitments_unavailable": True,
        },
        "match_keys_exact": policy["match_keys"] == ["receipt_sha256", "flight_id_plus_run_attempt"],
        "no_candidate_fabrication": policy["candidate_ids_fabricated"] is False,
        "no_manual_reconstruction": policy["fuzzy_or_manual_identity_reconstruction"] is False,
        "not_outcome_conditioned": policy["outcome_value_based_exclusion"] is False,
        "provenance_wide": policy["scope"] == "provenance_wide_not_outcome_conditioned",
        "beacon_source_exact": randomness["source"] == "NIST Randomness Beacon 2.0",
        "beacon_time_exact": randomness["earliest_acceptable_pulse_utc"] == "2026-08-08T00:00:00Z",
        "beacon_unconsumed": randomness["pulse_consumed"] is False,
        "beacon_unbound": randomness["pulse_uri"] is None and randomness["pulse_output_commitment_sha256"] is None,
        "governance_closed": governance == {
            "cohort_selected": False,
            "fresh_outcome_accessed": False,
            "analysis_executed": False,
            "stage10_unblocked": False,
            "production_modified": False,
            "merge_authorized": False,
            "external_cost_usd": 0.0,
            "scientific_promotion_credit": 0,
        },
        "all_receipts_excluded": all(lineage_is_excluded(registry, receipt_sha256=value) for value in receipts),
        "all_flights_excluded": all(lineage_is_excluded(registry, flight_id=flight, run_attempt=attempt) for flight, attempt in flights),
        "unknown_receipt_not_excluded": not lineage_is_excluded(registry, receipt_sha256="0" * 64),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(failed)
    return checks
