from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from fin_rvi_002_stage2.run_stage2 import (
    POLICIES,
    build_report,
    compact_rows,
    evaluate_policies,
    policy_promotes,
    rotate_documentary_decisions,
    sha256_payload,
)


class Stage2Tests(unittest.TestCase):
    def synthetic_rows(self):
        return [
            {
                "candidate_id": "positive",
                "shared_code": "CODE:A",
                "amount_sefin": 100,
                "relative_amount_difference": 0.2,
                "object_adjudication": {
                    "supplier_identity_supported": True,
                    "decision": "SUPPORTED",
                },
                "oncae_object_text": "SIT-GA-001-2024 sellos Print Color",
                "sefin_object_text": "Pago sellos Print Color",
            },
            {
                "candidate_id": "negative",
                "shared_code": "CODE:B",
                "amount_sefin": 50,
                "relative_amount_difference": 0.01,
                "object_adjudication": {
                    "supplier_identity_supported": True,
                    "decision": "REJECTED",
                },
                "oncae_object_text": "SIT-GA-001-2024 contrato de sellos",
                "sefin_object_text": "Pago publicación periódico aviso de prensa",
            },
        ]

    def test_policy_definitions(self):
        positive, negative = self.synthetic_rows()
        self.assertTrue(policy_promotes(negative, "B0_CODE"))
        self.assertTrue(policy_promotes(negative, "B1_CODE_SUPPLIER"))
        self.assertTrue(policy_promotes(negative, "B2_CODE_SUPPLIER_AMOUNT"))
        self.assertFalse(policy_promotes(negative, "POLICY_DOCUMENTARY"))
        self.assertTrue(policy_promotes(positive, "POLICY_DOCUMENTARY"))
        self.assertFalse(policy_promotes(positive, "B2_CODE_SUPPLIER_AMOUNT"))

    def test_documentary_policy_dominates_strong_baseline_on_synthetic_gold(self):
        compact = compact_rows(self.synthetic_rows())
        metrics = evaluate_policies(compact)
        self.assertEqual(metrics["B1_CODE_SUPPLIER"]["unsafe_overpromotions"], 1)
        self.assertEqual(metrics["POLICY_DOCUMENTARY"]["unsafe_overpromotions"], 0)
        self.assertEqual(metrics["POLICY_DOCUMENTARY"]["supported_recovered"], 1)

    def test_rotation_is_deterministic(self):
        compact = compact_rows(self.synthetic_rows())
        self.assertEqual(
            rotate_documentary_decisions(compact),
            rotate_documentary_decisions(copy.deepcopy(compact)),
        )

    def test_real_report_is_deterministic(self):
        source = Path("reports/fin_rvi_002_stage1")
        rows = [
            json.loads(line)
            for line in (source / "holdout_decisions.jsonl").read_text().splitlines()
            if line
        ]
        source_report = json.loads((source / "report.json").read_text())
        first = build_report(rows, source_report)
        second = build_report(rows, source_report)
        self.assertEqual(first, second)
        self.assertEqual(first["sha256"], sha256_payload(first["payload"]))
        self.assertEqual(set(first["payload"]["policy_metrics"]), set(POLICIES))

    def test_report_tamper_changes_hash(self):
        source = Path("reports/fin_rvi_002_stage1")
        rows = [
            json.loads(line)
            for line in (source / "holdout_decisions.jsonl").read_text().splitlines()
            if line
        ]
        report = build_report(rows, json.loads((source / "report.json").read_text()))
        altered = copy.deepcopy(report)
        altered["payload"]["selected_policy"] = "B0_CODE"
        self.assertNotEqual(altered["sha256"], sha256_payload(altered["payload"]))


if __name__ == "__main__":
    unittest.main()
