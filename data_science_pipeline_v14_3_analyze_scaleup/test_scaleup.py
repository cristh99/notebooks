from __future__ import annotations

import json
import os
import unittest
from datetime import timezone
from pathlib import Path

from scaleup import canonical, exact_bid_count, fisher_two_sided, median_mad, parse_date, releases_from, sha256, wilson


ROOT = Path(os.environ.get("SCALEUP_OUTPUT_DIR", "runtime"))
PROTOCOL = Path(os.environ.get("SCALEUP_PROTOCOL", "PREREGISTERED_SCALEUP_PROTOCOL.json"))
FREEZE = Path(os.environ.get("SCALEUP_FREEZE", "FREEZE.json"))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class FunctionTests(unittest.TestCase):
    def test_01_canonical_order(self):
        self.assertEqual(canonical({"b": 1, "a": 2}), b'{"a":2,"b":1}\n')

    def test_02_parse_date_z(self):
        self.assertEqual(parse_date("2024-01-02T03:04:05Z").tzinfo, timezone.utc)

    def test_03_parse_date_naive(self):
        self.assertEqual(parse_date("2024-01-02T03:04:05").tzinfo, timezone.utc)

    def test_04_parse_date_invalid(self):
        self.assertIsNone(parse_date("not-a-date"))

    def test_05_releases_package(self):
        self.assertEqual(releases_from({"releases": [{"id": "x"}]}), [{"id": "x"}])

    def test_06_releases_records_compiled(self):
        self.assertEqual(releases_from({"records": [{"compiledRelease": {"id": "x"}}]}), [{"id": "x"}])

    def test_07_releases_records_releases(self):
        self.assertEqual(releases_from({"records": [{"releases": [{"id": "x"}]}]}), [{"id": "x"}])

    def test_08_releases_single(self):
        self.assertEqual(releases_from({"ocid": "x"}), [{"ocid": "x"}])

    def test_09_releases_invalid(self):
        self.assertEqual(releases_from([]), [])

    def test_10_bid_explicit_int(self):
        self.assertEqual(exact_bid_count({"numberOfTenderers": 3})[:2], (3, "numberOfTenderers"))

    def test_11_bid_explicit_string(self):
        self.assertEqual(exact_bid_count({"numberOfTenderers": "4"})[:2], (4, "numberOfTenderers"))

    def test_12_bid_explicit_float(self):
        self.assertEqual(exact_bid_count({"numberOfTenderers": 2.0})[:2], (2, "numberOfTenderers"))

    def test_13_bid_boolean_missing(self):
        self.assertIsNone(exact_bid_count({"numberOfTenderers": True})[0])

    def test_14_bid_empty_array_missing(self):
        self.assertEqual(exact_bid_count({"tenderers": []})[:2], (None, "NOT_REPORTED_IN_SOURCE"))

    def test_15_bid_nonempty_ids(self):
        self.assertEqual(exact_bid_count({"tenderers": [{"id": "a"}, {"id": "b"}]})[:2], (2, "nonempty_tenderers_distinct"))

    def test_16_bid_duplicate_ids(self):
        self.assertEqual(exact_bid_count({"tenderers": [{"id": "a"}, {"id": "a"}]})[0], 1)

    def test_17_bid_names(self):
        self.assertEqual(exact_bid_count({"tenderers": [{"name": " A  Corp "}, {"name": "A Corp"}]})[0], 1)

    def test_18_bid_conflict(self):
        value, reason, detail = exact_bid_count({"numberOfTenderers": 1, "tenderers": [{"id": "a"}, {"id": "b"}]})
        self.assertIsNone(value)
        self.assertEqual(reason, "CONFLICT_EXPLICIT_VS_TENDERERS")
        self.assertEqual(detail["tenderers_distinct"], 2)

    def test_19_fisher_symmetric(self):
        self.assertAlmostEqual(fisher_two_sided(5, 5, 5, 5), 1.0)

    def test_20_fisher_bounds(self):
        self.assertGreaterEqual(fisher_two_sided(4, 6, 2, 8), 0.0)
        self.assertLessEqual(fisher_two_sided(4, 6, 2, 8), 1.0)

    def test_21_fisher_extreme(self):
        self.assertLess(fisher_two_sided(10, 0, 0, 10), 0.001)

    def test_22_wilson_empty(self):
        self.assertEqual(wilson(0, 0), [None, None])

    def test_23_wilson_bounds(self):
        lower, upper = wilson(3, 10)
        self.assertTrue(0.0 <= lower <= upper <= 1.0)

    def test_24_median_mad_empty(self):
        self.assertEqual(median_mad([]), (None, None))

    def test_25_median_mad_simple(self):
        self.assertEqual(median_mad([1, 2, 3]), (2, 1))

    def test_26_median_mad_constant(self):
        self.assertEqual(median_mad([2, 2, 2]), (2, 0))


class FrozenOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = read_json(PROTOCOL)
        cls.freeze = read_json(FREEZE)
        cls.source = read_json(ROOT / "SOURCE_IDENTITY.json")
        cls.result = read_json(ROOT / "SCALEUP_RESULT.json")
        cls.manifest = read_json(ROOT / "SCALEUP_MANIFEST.json")
        cls.cohort = read_jsonl(ROOT / "SCALEUP_COHORT.jsonl")
        cls.quarantines = read_jsonl(ROOT / "QUARANTINE.jsonl")
        cls.groups = {group: [row for row in cls.cohort if row["method_group"] == group] for group in ("DIRECT", "OPEN")}

    def test_27_protocol_frozen(self):
        self.assertEqual(self.protocol["status"], "FROZEN_BEFORE_COHORT_DISCOVERY")
        self.assertFalse(self.freeze["source_bytes_accessed_before_freeze"])

    def test_28_source_identity(self):
        self.assertEqual(self.source["publication_id"], 122)
        self.assertEqual(len(self.source["sha256"]), 64)

    def test_29_result_terminal(self):
        self.assertEqual(self.result["terminal"], "ANALYSIS_EXECUTION_VALIDATED")
        self.assertEqual(self.result["reason"], "BOUNDED_PREREGISTERED_CANARY_SUFFICIENT")

    def test_30_manifest_hashes(self):
        for name, expected in self.manifest["files"].items():
            path = ROOT / name
            self.assertEqual(path.stat().st_size, expected["bytes"])
            self.assertEqual(sha256(path.read_bytes()), expected["sha256"])

    def test_31_cohort_nonempty(self):
        self.assertEqual(len(self.cohort), self.manifest["selected_rows"])
        self.assertGreater(len(self.cohort), 0)

    def test_32_group_minimum(self):
        self.assertGreaterEqual(len(self.groups["DIRECT"]), 5)
        self.assertGreaterEqual(len(self.groups["OPEN"]), 5)

    def test_33_target_limit(self):
        self.assertLessEqual(len(self.groups["DIRECT"]), 20)
        self.assertLessEqual(len(self.groups["OPEN"]), 20)

    def test_34_unique_event_ids(self):
        self.assertEqual(len({row["event_id"] for row in self.cohort}), len(self.cohort))

    def test_35_one_per_ocid(self):
        self.assertEqual(len({row["ocid_commitment_sha256"] for row in self.cohort}), len(self.cohort))

    def test_36_roles(self):
        self.assertTrue(all((row["event_role"], row["amount_role"], row["date_role"]) == ("CONTRACT", "CONTRACT_VALUE", "CONTRACT_DATE") for row in self.cohort))

    def test_37_method_group(self):
        self.assertEqual({row["method_group"] for row in self.cohort}, {"DIRECT", "OPEN"})
        self.assertTrue(all(row["procurement_method"] == row["method_group"].lower() for row in self.cohort))

    def test_38_bid_outcome(self):
        self.assertTrue(all(isinstance(row["bid_count"], int) and row["low_competition"] is (row["bid_count"] <= 1) for row in self.cohort))

    def test_39_no_raw_identity(self):
        forbidden = {"buyer_id", "buyer_name", "supplier_id", "supplier_name", "ocid", "contract_id"}
        self.assertTrue(all(not (forbidden & set(row)) for row in self.cohort))

    def test_40_lineage(self):
        self.assertTrue(all(row["lineage"]["archive_sha256"] == self.source["sha256"] for row in self.cohort))
        self.assertTrue(all(row["lineage"]["compressed_byte_count"] == self.source["bytes"] for row in self.cohort))

    def test_41_record_hash(self):
        self.assertTrue(all(row["record_sha256"] == sha256(canonical({key: value for key, value in row.items() if key != "record_sha256"})) for row in self.cohort))

    def test_42_dates(self):
        self.assertTrue(all(row["event_date"] <= "2025-12-31" for row in self.cohort))

    def test_43_currency_amount(self):
        self.assertTrue(all(row["currency"] == "HNL" and row["amount_hnl_cents"] > 0 for row in self.cohort))

    def test_44_contingency(self):
        for group in ("DIRECT", "OPEN"):
            successes = sum(row["low_competition"] for row in self.groups[group])
            cell = self.result["contingency"][group]
            self.assertEqual(cell["low_competition"], successes)
            self.assertEqual(cell["n"], len(self.groups[group]))

    def test_45_fisher_bh(self):
        direct = self.result["contingency"]["DIRECT"]
        opened = self.result["contingency"]["OPEN"]
        expected = fisher_two_sided(direct["low_competition"], direct["not_low_competition"], opened["low_competition"], opened["not_low_competition"])
        self.assertAlmostEqual(self.result["fisher_two_sided_p"], expected)
        self.assertEqual(self.result["bh_adjusted_p"], self.result["fisher_two_sided_p"])

    def test_46_negative_control(self):
        self.assertFalse(self.result["negative_control"]["promoted"])

    def test_47_governance(self):
        self.assertFalse(self.result["governance"]["stage10_unblocked"])
        self.assertFalse(self.result["governance"]["production_modified"])
        self.assertEqual(self.result["governance"]["external_cost_usd"], 0.0)

    def test_48_deterministic_order(self):
        expected = sorted(self.cohort, key=lambda row: (row["method_group"], sha256(row["event_id"].encode())))
        self.assertEqual(self.cohort, expected)

    def test_49_quarantine_count(self):
        self.assertEqual(len(self.quarantines), self.result["quarantine_count"])

    def test_50_result_canonical(self):
        self.assertEqual((ROOT / "SCALEUP_RESULT.json").read_bytes(), canonical(self.result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
