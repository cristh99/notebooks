from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from fin_rvi_002_g09.verify_claim import build_receipt, digest, verify
from fin_rvi_002_g09.verify_prior_art import build_receipt as build_prior_receipt
from fin_rvi_002_g09.verify_prior_art import verify as verify_prior


class G09ClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(
            Path("fin_rvi_002_g09/claim_contract.json").read_text(encoding="utf-8")
        )
        cls.prior = json.loads(
            Path("fin_rvi_002_g09/prior_art_search_log_20260803.json").read_text(encoding="utf-8")
        )

    def test_contract_is_valid_and_passes(self) -> None:
        self.assertEqual(verify(self.contract), [])
        receipt = build_receipt(self.contract)
        self.assertTrue(receipt["payload"]["valid"])
        self.assertEqual(receipt["payload"]["status"], "PASS")
        self.assertTrue(receipt["payload"]["promotion_allowed"])
        self.assertEqual(receipt["payload"]["passed_required_gates"], 5)
        self.assertEqual(receipt["payload"]["gate_readout"]["finance_score"], 1000)

    def test_prior_art_log_is_valid(self) -> None:
        self.assertEqual(verify_prior(self.prior), [])
        receipt = build_prior_receipt(self.prior)
        self.assertTrue(receipt["payload"]["bounded_search_pass"])
        self.assertFalse(receipt["payload"]["exact_claim_match_found"])

    def test_claim_cannot_expand_to_fraud(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["scope"]["excluded_claims"].remove("fraud")
        self.assertIn("excluded-claims", verify(altered))

    def test_broad_method_novelty_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["novelty_classification"]["broad_method_novelty"] = True
        self.assertIn("broad-method-novelty", verify(altered))

    def test_absorbed_prior_art_cannot_be_reclaimed(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["prior_art_absorbed"].remove("public_payment_record_linkage")
        self.assertIn("prior-art-boundary", verify(altered))

    def test_pass_with_open_gate_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["current_gates"]["clean_independent_replay"] = "PENDING"
        self.assertIn("premature-pass", verify(altered))

    def test_stale_open_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["status"] = "OPEN"
        self.assertIn("stale-open", verify(altered))

    def test_empirical_result_tamper_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["empirical_evidence"]["independent_stage4"]["challenger_v3"]["unsafe_overpromotions"] = 1
        self.assertIn("stage4-result", verify(altered))

    def test_prior_art_exact_match_blocks_claim(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["novelty_classification"]["exact_claim_match_found_in_bounded_search"] = True
        self.assertIn("prior-art-exact-match", verify(altered))

    def test_prior_art_log_requires_exact_match_false(self) -> None:
        altered = copy.deepcopy(self.prior)
        altered["component_disposition"]["exact_claim_match_found"] = True
        self.assertIn("exact-match", verify_prior(altered))

    def test_digest_is_deterministic(self) -> None:
        self.assertEqual(digest(self.contract), digest(copy.deepcopy(self.contract)))


if __name__ == "__main__":
    unittest.main()
