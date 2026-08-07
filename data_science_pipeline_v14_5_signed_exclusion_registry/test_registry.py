from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from registry import EXPECTED, SCOPE, lineage_is_excluded, validate_registry

HERE = Path(__file__).resolve().parent
REGISTRY = json.loads((HERE / "EXCLUSION_REGISTRY.json").read_text())


class RegistryTests(unittest.TestCase):
    def test_01_all_checks(self): self.assertTrue(all(validate_registry(REGISTRY).values()))
    def test_02_schema(self): self.assertTrue(validate_registry(REGISTRY)["schema_exact"])
    def test_03_coordination(self): self.assertTrue(validate_registry(REGISTRY)["coordination_exact"])
    def test_04_stage(self): self.assertTrue(validate_registry(REGISTRY)["stage_exact"])
    def test_05_status(self): self.assertTrue(validate_registry(REGISTRY)["status_exact"])
    def test_06_canonical_pr(self): self.assertEqual(REGISTRY["authority"]["canonical_stage09_pr"], 153)
    def test_07_canonical_head(self): self.assertEqual(REGISTRY["authority"]["canonical_stage09_head"], "499ff89d5c2b8a97b70f1d871d64345875192f98")
    def test_08_recovery_pr(self): self.assertEqual(REGISTRY["authority"]["recovery_protocol_pr"], 161)
    def test_09_recovery_head(self): self.assertEqual(REGISTRY["authority"]["recovery_protocol_head"], "9eba1bdec80dc9fedd763bb1d0afc9637203c3b4")
    def test_10_recovery_hash(self): self.assertTrue(validate_registry(REGISTRY)["recovery_hash_exact"])
    def test_11_ledger_hash(self): self.assertTrue(validate_registry(REGISTRY)["ledger_hash_exact"])
    def test_12_entry_count(self): self.assertEqual(len(REGISTRY["entries"]), 8)
    def test_13_entry_set(self): self.assertTrue(validate_registry(REGISTRY)["entry_set_exact"])
    def test_14_receipt_validity(self): self.assertTrue(validate_registry(REGISTRY)["receipt_hashes_valid"])
    def test_15_receipt_uniqueness(self): self.assertTrue(validate_registry(REGISTRY)["receipt_hashes_unique"])
    def test_16_flight_validity(self): self.assertTrue(validate_registry(REGISTRY)["flight_keys_valid"])
    def test_17_flight_uniqueness(self): self.assertTrue(validate_registry(REGISTRY)["flight_keys_unique"])
    def test_18_selected_count(self): self.assertEqual(sum(e["selected_candidate_count_disclosed"] for e in REGISTRY["entries"]), 26)
    def test_19_selected_nonnegative(self): self.assertTrue(validate_registry(REGISTRY)["selected_counts_nonnegative"])
    def test_20_outcome_count(self): self.assertEqual(sum(e["outcome_accessed"] for e in REGISTRY["entries"]), 7)
    def test_21_identity_count(self): self.assertEqual(sum(e["identity_accessed"] for e in REGISTRY["entries"]), 7)
    def test_22_commitments_unavailable(self): self.assertTrue(all(e["candidate_commitments_available"] is False for e in REGISTRY["entries"]))
    def test_23_scope_exact(self): self.assertTrue(all(e["exclusion_scope"] == SCOPE for e in REGISTRY["entries"]))
    def test_24_aggregate_exact(self): self.assertTrue(validate_registry(REGISTRY)["aggregate_exact"])
    def test_25_match_keys(self): self.assertTrue(validate_registry(REGISTRY)["match_keys_exact"])
    def test_26_no_fabrication(self): self.assertFalse(REGISTRY["exclusion_policy"]["candidate_ids_fabricated"])
    def test_27_no_manual_reconstruction(self): self.assertFalse(REGISTRY["exclusion_policy"]["fuzzy_or_manual_identity_reconstruction"])
    def test_28_not_outcome_conditioned(self): self.assertFalse(REGISTRY["exclusion_policy"]["outcome_value_based_exclusion"])
    def test_29_provenance_wide(self): self.assertEqual(REGISTRY["exclusion_policy"]["scope"], "provenance_wide_not_outcome_conditioned")
    def test_30_beacon_time(self): self.assertEqual(REGISTRY["future_randomness"]["earliest_acceptable_pulse_utc"], "2026-08-08T00:00:00Z")
    def test_31_beacon_unconsumed(self): self.assertFalse(REGISTRY["future_randomness"]["pulse_consumed"])
    def test_32_governance_closed(self): self.assertTrue(validate_registry(REGISTRY)["governance_closed"])
    def test_33_all_receipts_excluded(self): self.assertTrue(validate_registry(REGISTRY)["all_receipts_excluded"])
    def test_34_all_flights_excluded(self): self.assertTrue(validate_registry(REGISTRY)["all_flights_excluded"])
    def test_35_unknown_receipt_not_excluded(self): self.assertFalse(lineage_is_excluded(REGISTRY, receipt_sha256="0" * 64))
    def test_36_missing_provenance_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "missing provenance"):
            lineage_is_excluded(REGISTRY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
