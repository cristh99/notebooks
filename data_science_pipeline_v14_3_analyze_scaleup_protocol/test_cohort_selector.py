from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cohort_selector as c


HERE = Path(__file__).resolve().parent
PROTOCOL = json.loads((HERE / "SCALE_UP_PROTOCOL.json").read_text())


def row(index: int, method: str = "direct", **updates):
    value = {
        "event_commitment_sha256": hashlib.sha256(f"event-{index}".encode()).hexdigest(),
        "procurement_method": method,
        "event_role": "CONTRACT",
        "amount_role": "CONTRACT_VALUE",
        "date_role": "CONTRACT_DATE",
        "currency": "HNL",
        "event_date": "2025-01-15",
        "resolution_state": "MATCH_OFFICIAL",
        "lineage_sha256": hashlib.sha256(f"lineage-{index}".encode()).hexdigest(),
    }
    value.update(updates)
    return value


def full_fixture():
    return [row(i, "direct") for i in range(20)] + [row(i + 100, "open") for i in range(20)]


class CohortSelectorTests(unittest.TestCase):
    def baseline(self):
        return c.select(full_fixture(), PROTOCOL)

    def test_01_canonical_newline(self):
        self.assertTrue(c.canonical_bytes({"b": 1, "a": 2}).endswith(b"\n"))

    def test_02_selection_key_stable(self):
        value = row(1)["event_commitment_sha256"]
        self.assertEqual(c.selection_key("seed", value), c.selection_key("seed", value))

    def test_03_direct_mapping(self):
        group, _ = c.validate_candidate(row(1, "direct"), PROTOCOL)
        self.assertEqual(group, "DIRECT")

    def test_04_open_mapping(self):
        group, _ = c.validate_candidate(row(1, "open"), PROTOCOL)
        self.assertEqual(group, "OPEN")

    def test_05_other_method_excluded(self):
        group, _ = c.validate_candidate(row(1, "selective"), PROTOCOL)
        self.assertIsNone(group)

    def test_06_non_contract_excluded(self):
        group, _ = c.validate_candidate(row(1, event_role="PAYMENT"), PROTOCOL)
        self.assertIsNone(group)

    def test_07_wrong_amount_role_excluded(self):
        group, _ = c.validate_candidate(row(1, amount_role="PAYMENT_VALUE"), PROTOCOL)
        self.assertIsNone(group)

    def test_08_wrong_date_role_excluded(self):
        group, _ = c.validate_candidate(row(1, date_role="PAYMENT_DATE"), PROTOCOL)
        self.assertIsNone(group)

    def test_09_wrong_currency_excluded(self):
        group, _ = c.validate_candidate(row(1, currency="USD"), PROTOCOL)
        self.assertIsNone(group)

    def test_10_unresolved_excluded(self):
        group, _ = c.validate_candidate(row(1, resolution_state="CANDIDATE_REVIEW"), PROTOCOL)
        self.assertIsNone(group)

    def test_11_after_cutoff_excluded(self):
        group, _ = c.validate_candidate(row(1, event_date="2026-01-01"), PROTOCOL)
        self.assertIsNone(group)

    def test_12_fixture_rows(self):
        self.assertEqual(len(full_fixture()), 40)

    def test_13_terminal_frozen(self):
        self.assertEqual(self.baseline()["terminal_state"], "COHORT_FROZEN_BLIND")

    def test_14_candidate_count(self):
        self.assertEqual(self.baseline()["input"]["candidate_rows"], 40)

    def test_15_eligible_counts(self):
        self.assertEqual(self.baseline()["input"]["eligible_counts"], {"DIRECT": 20, "OPEN": 20})

    def test_16_selected_count(self):
        self.assertEqual(self.baseline()["sampling"]["selected_event_count"], 40)

    def test_17_direct_primary_ten(self):
        self.assertEqual(len(self.baseline()["sampling"]["selected"]["DIRECT"]["primary"]), 10)

    def test_18_direct_reserve_ten(self):
        self.assertEqual(len(self.baseline()["sampling"]["selected"]["DIRECT"]["reserve"]), 10)

    def test_19_open_primary_ten(self):
        self.assertEqual(len(self.baseline()["sampling"]["selected"]["OPEN"]["primary"]), 10)

    def test_20_open_reserve_ten(self):
        self.assertEqual(len(self.baseline()["sampling"]["selected"]["OPEN"]["reserve"]), 10)

    def test_21_outcome_reveal_allowed_after_freeze(self):
        self.assertIs(self.baseline()["readiness"]["outcome_reveal_allowed"], True)

    def test_22_analysis_not_allowed(self):
        self.assertIs(self.baseline()["readiness"]["analysis_allowed"], False)

    def test_23_stage10_blocked(self):
        self.assertIs(self.baseline()["readiness"]["stage10_unblocked"], False)

    def test_24_outcome_not_accessed(self):
        self.assertIs(self.baseline()["blinding"]["outcome_accessed"], False)

    def test_25_bid_count_not_accessed(self):
        self.assertIs(self.baseline()["blinding"]["bid_count_accessed"], False)

    def test_26_raw_identity_not_exported(self):
        self.assertIs(self.baseline()["blinding"]["raw_identity_exported"], False)

    def test_27_row_order_invariant(self):
        left = self.baseline()
        right = c.select(list(reversed(full_fixture())), PROTOCOL)
        self.assertEqual(c.canonical_bytes(left), c.canonical_bytes(right))

    def test_28_deterministic_hash(self):
        self.assertEqual(c.sha256_value(self.baseline()), c.sha256_value(self.baseline()))

    def test_29_duplicate_commitment_fails(self):
        duplicate = row(1)
        with self.assertRaisesRegex(c.ProtocolError, "DUPLICATE_EVENT_COMMITMENT"):
            c.select([duplicate, copy.deepcopy(duplicate)], PROTOCOL)

    def test_30_invalid_event_hash_fails(self):
        with self.assertRaisesRegex(c.ProtocolError, "INVALID_SHA256:event_commitment_sha256"):
            c.validate_candidate(row(1, event_commitment_sha256="bad"), PROTOCOL)

    def test_31_invalid_lineage_hash_fails(self):
        with self.assertRaisesRegex(c.ProtocolError, "INVALID_SHA256:lineage_sha256"):
            c.validate_candidate(row(1, lineage_sha256="bad"), PROTOCOL)

    def test_32_missing_required_field_fails(self):
        value = row(1)
        value.pop("currency")
        with self.assertRaisesRegex(c.ProtocolError, "MISSING_REQUIRED_FIELDS:currency"):
            c.validate_candidate(value, PROTOCOL)

    def test_33_invalid_date_fails(self):
        with self.assertRaisesRegex(c.ProtocolError, "INVALID_EVENT_DATE"):
            c.validate_candidate(row(1, event_date="not-a-date"), PROTOCOL)

    def test_34_insufficient_group_terminal(self):
        records = [row(i, "direct") for i in range(20)] + [row(i + 100, "open") for i in range(19)]
        self.assertEqual(c.select(records, PROTOCOL)["terminal_state"], "COHORT_NOT_EVALUABLE_INSUFFICIENT_ELIGIBLE_EVENTS")

    def test_35_insufficient_manifest_selects_nothing(self):
        records = [row(i, "direct") for i in range(20)] + [row(i + 100, "open") for i in range(19)]
        selected = c.select(records, PROTOCOL)["sampling"]["selected"]
        self.assertTrue(all(not parts["primary"] and not parts["reserve"] for parts in selected.values()))


def _forbidden_test(field):
    def test(self):
        value = row(999)
        value[field] = 0
        with self.assertRaisesRegex(c.ProtocolError, "FORBIDDEN_DISCOVERY_FIELDS"):
            c.validate_candidate(value, PROTOCOL)
    return test


for _index, _field in enumerate(PROTOCOL["discovery_blinding"]["forbidden_fields"], start=36):
    setattr(CohortSelectorTests, f"test_{_index:02d}_forbid_{_field}", _forbidden_test(_field))


if __name__ == "__main__":
    unittest.main(verbosity=2)
