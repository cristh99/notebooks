from __future__ import annotations

import copy
import unittest

from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    FAIL_FULL_EXTERNAL_GATE,
    PASS_FULL_EXTERNAL_GATE,
    PARTITION_COUNT,
)
from ocr_real_risk_v1.openvino_full_gate_v7 import aggregate_partition_reports
from ocr_real_risk_v1.test_openvino_full_gate_v7 import AggregateTests, h


class MacrofoldSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        helper = AggregateTests(methodName="test_exact_summary_rejects_counterfactual_or_low_coverage")
        helper.setUp()
        self.helper = helper

    def aggregate(self, reports: list[dict]) -> dict:
        return aggregate_partition_reports(
            reports,
            expected_partition_counts=[40] * PARTITION_COUNT,
            registry_stable_payload_sha256=h("registry"),
            expected_code_bundle=self.helper.bundle,
            authorization_binding=self.helper.binding,
            minimum_active=1,
        )

    def fail_macrofolds(self, count: int) -> list[dict]:
        reports = self.helper.make_reports(40)
        for partition in range(count * 3):
            rows = copy.deepcopy(reports[partition]["observations"])
            for row in rows:
                row["candidate"]["accepted"] = False
                row["candidate"]["false_accept"] = False
            reports[partition] = self.helper.report(partition, rows)
        return reports

    def test_each_detail_is_exactly_one_declared_three_partition_macrofold(self):
        result = self.aggregate(self.fail_macrofolds(0))
        self.assertEqual(result["stability"]["semantics"], "each_preregistered_macrofold")
        self.assertEqual(
            [row["partitions"] for row in result["stability"]["details"]],
            [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]],
        )
        self.assertEqual(
            [row["summary"]["selected"] for row in result["stability"]["details"]],
            [120, 120, 120, 120],
        )

    def test_exactly_three_of_four_macrofolds_pass(self):
        result = self.aggregate(self.fail_macrofolds(1))
        self.assertEqual(result["stability"]["passes"], 3)
        self.assertTrue(result["stability"]["pass"])
        self.assertEqual(result["status"], PASS_FULL_EXTERNAL_GATE)

    def test_two_of_four_macrofolds_fail_the_scientific_gate(self):
        result = self.aggregate(self.fail_macrofolds(2))
        self.assertEqual(result["stability"]["passes"], 2)
        self.assertFalse(result["stability"]["pass"])
        self.assertEqual(result["status"], FAIL_FULL_EXTERNAL_GATE)


if __name__ == "__main__":
    unittest.main()
