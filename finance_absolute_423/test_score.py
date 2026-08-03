from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from finance_absolute_423.verify_score import EXPECTED_ACTION, verify


class AbsoluteFinanceScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scorecard = json.loads(
            Path("finance_absolute_423/scorecard.json").read_text(encoding="utf-8")
        )

    def test_canonical_scorecard_passes(self) -> None:
        receipt = verify(self.scorecard)
        self.assertTrue(receipt["payload"]["valid"])
        self.assertEqual(receipt["payload"]["absolute_score"], 423)
        self.assertEqual(receipt["payload"]["selected_action"], EXPECTED_ACTION)

    def test_forged_1000_fails(self) -> None:
        altered = copy.deepcopy(self.scorecard)
        altered["absolute_score"] = 1000
        receipt = verify(altered)
        self.assertFalse(receipt["payload"]["valid"])
        self.assertFalse(receipt["payload"]["gates"]["declared_score_423"])
        self.assertFalse(receipt["payload"]["gates"]["open_points_577"])

    def test_universal_scope_fails(self) -> None:
        altered = copy.deepcopy(self.scorecard)
        altered["maximum_claim"] = "universal finance SOTA"
        receipt = verify(altered)
        self.assertFalse(receipt["payload"]["valid"])
        self.assertFalse(receipt["payload"]["gates"]["maximum_claim_bounded"])

    def test_reclaiming_internal_1000_fails(self) -> None:
        altered = copy.deepcopy(self.scorecard)
        altered["superseded_interpretations"]["1000"] = "all of finance"
        receipt = verify(altered)
        self.assertFalse(receipt["payload"]["valid"])
        self.assertFalse(receipt["payload"]["gates"]["internal_scores_demoted"])

    def test_narrow_result_cannot_imply_global_sota(self) -> None:
        altered = copy.deepcopy(self.scorecard)
        altered["bounded_result"]["does_not_imply"].remove("global finance SOTA")
        receipt = verify(altered)
        self.assertFalse(receipt["payload"]["valid"])
        self.assertFalse(receipt["payload"]["gates"]["fin_rvi_scope_bounded"])

    def test_score_change_without_evidence_fails(self) -> None:
        altered = copy.deepcopy(self.scorecard)
        altered["dimensions"][0]["score"] = 250
        receipt = verify(altered)
        self.assertFalse(receipt["payload"]["valid"])
        self.assertFalse(receipt["payload"]["gates"]["scores_exact"])

    def test_wrong_action_fails(self) -> None:
        altered = copy.deepcopy(self.scorecard)
        altered["selected_action"] = "more_internal_theory"
        receipt = verify(altered)
        self.assertFalse(receipt["payload"]["valid"])
        self.assertFalse(receipt["payload"]["gates"]["selected_action_exact"])

    def test_utility_forgery_changes_recomputed_action_or_exact_contract(self) -> None:
        altered = copy.deepcopy(self.scorecard)
        for state in altered["problem_ir"]["actions"]["more_internal_theory"]:
            altered["problem_ir"]["actions"]["more_internal_theory"][state] = 1000
        receipt = verify(altered)
        self.assertFalse(receipt["payload"]["valid"])
        self.assertFalse(receipt["payload"]["gates"]["minimax_recomputed"])
        self.assertFalse(receipt["payload"]["gates"]["more_theory_not_selected"])


if __name__ == "__main__":
    unittest.main()
