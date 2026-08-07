from __future__ import annotations

import copy
import unittest

from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    ABSTAIN_DEDUP_OR_INTEGRITY,
    PARTITION_COUNT,
    stable_payload,
)
from ocr_real_risk_v1.openvino_full_gate_v7 import aggregate_partition_reports
from ocr_real_risk_v1.test_openvino_full_gate_v7 import AggregateTests, h


class AggregateRegistryBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        helper = AggregateTests(methodName="test_exact_summary_rejects_counterfactual_or_low_coverage")
        helper.setUp()
        self.helper = helper
        self.reports = helper.make_reports(8)
        self.expected: dict[int, list[dict]] = {}
        for partition, report in enumerate(self.reports):
            rows: list[dict] = []
            for index, observation in enumerate(report["observations"]):
                rank = h(f"rank:{partition}:{index}")
                observation["selection_rank_sha256"] = rank
                rows.append(
                    {
                        "row_index": observation["row_index"],
                        "image_id": observation["image_id"],
                        "partition": partition,
                        "selection_rank_sha256": rank,
                        "encoded_sha256": observation["encoded_sha256"],
                        "pixel_sha256": observation["pixel_sha256"],
                    }
                )
            self.reports[partition] = helper.report(
                partition, report["observations"]
            )
            self.expected[partition] = rows

    def aggregate(self, reports: list[dict] | None = None, expected: dict | None = None):
        return aggregate_partition_reports(
            reports or self.reports,
            expected_partition_counts=[8] * PARTITION_COUNT,
            registry_stable_payload_sha256=h("registry"),
            expected_code_bundle=self.helper.bundle,
            authorization_binding=self.helper.binding,
            expected_registry_rows=expected or self.expected,
            minimum_active=1,
        )

    def test_clean_reports_match_exact_active_registry_rows(self):
        result = self.aggregate()
        self.assertEqual(result["execution"]["selected"], 96)

    def test_report_row_cannot_claim_another_partition(self):
        reports = copy.deepcopy(self.reports)
        reports[0]["observations"][0]["partition_id"] = 1
        reports[0] = stable_payload(
            {
                key: value
                for key, value in reports[0].items()
                if key != "stable_payload_sha256"
            }
        )
        with self.assertRaises(RuntimeError):
            self.aggregate(reports=reports)

    def test_registry_hash_or_selection_rank_substitution_is_rejected(self):
        for field, value in (
            ("pixel_sha256", h("substituted-pixels")),
            ("selection_rank_sha256", h("substituted-rank")),
        ):
            expected = copy.deepcopy(self.expected)
            expected[0][0][field] = value
            with self.assertRaises(RuntimeError):
                self.aggregate(expected=expected)

    def test_abstain_explicitly_forbids_post_outcome_retry(self):
        reports = copy.deepcopy(self.reports)
        reports[1]["observations"][0]["pixel_sha256"] = reports[0][
            "observations"
        ][0]["pixel_sha256"]
        reports[1] = self.helper.report(1, reports[1]["observations"])
        expected = copy.deepcopy(self.expected)
        expected[1][0]["pixel_sha256"] = reports[1]["observations"][0][
            "pixel_sha256"
        ]
        result = self.aggregate(reports=reports, expected=expected)
        self.assertEqual(result["status"], ABSTAIN_DEDUP_OR_INTEGRITY)
        self.assertFalse(result["post_outcome_retry_authorized"])


if __name__ == "__main__":
    unittest.main()
