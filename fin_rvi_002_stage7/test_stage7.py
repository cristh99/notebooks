from __future__ import annotations

import unittest

from fin_rvi_002_stage7.verify_clean_replay import (
    combined_statistical_evidence,
    independent_policy_v3,
)


class Stage7Tests(unittest.TestCase):
    def row(self, **updates):
        base = {
            "policy_numeric_conflict": False,
            "policy_exact_numeric_support": False,
            "policy_name_support": False,
            "policy_payment_language": False,
            "policy_hard_category_conflict": False,
            "policy_shared_object_token_count": 0,
            "policy_shared_classifications": [],
            "policy_base_v2_decision": "UNRESOLVED",
        }
        base.update(updates)
        return base

    def test_numeric_identity_conflict_vetoes_promotion(self):
        result = independent_policy_v3(
            self.row(
                policy_numeric_conflict=True,
                policy_exact_numeric_support=True,
                policy_payment_language=True,
                policy_shared_object_token_count=20,
            )
        )
        self.assertEqual(result["decision"], "REJECTED")
        self.assertEqual(result["reason"], "V3_NUMERIC_SUPPLIER_CONFLICT_VETO")

    def test_exact_identifier_payment_and_object_support_promotes(self):
        result = independent_policy_v3(
            self.row(
                policy_exact_numeric_support=True,
                policy_payment_language=True,
                policy_shared_object_token_count=2,
            )
        )
        self.assertEqual(result["decision"], "SUPPORTED")
        self.assertEqual(result["reason"], "V3_EXACT_ID_PAYMENT_AND_OBJECT_SUPPORT")

    def test_name_only_path_requires_strong_joint_support(self):
        weak = independent_policy_v3(
            self.row(
                policy_name_support=True,
                policy_payment_language=True,
                policy_base_v2_decision="SUPPORTED",
                policy_shared_object_token_count=5,
            )
        )
        strong = independent_policy_v3(
            self.row(
                policy_name_support=True,
                policy_payment_language=True,
                policy_base_v2_decision="SUPPORTED",
                policy_shared_object_token_count=6,
            )
        )
        self.assertEqual(weak["decision"], "UNRESOLVED")
        self.assertEqual(strong["decision"], "SUPPORTED")

    def test_combined_statistics_are_bounded_not_universal(self):
        evidence = combined_statistical_evidence()
        self.assertEqual(evidence["corrected_unsafe_promotions"], 39)
        self.assertEqual(evidence["introduced_unsafe_promotions"], 0)
        self.assertEqual(evidence["supported_recovered"], 121)
        self.assertIn("not a global population guarantee", evidence["interpretation"])


if __name__ == "__main__":
    unittest.main()
