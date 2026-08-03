from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from fin_rvi_002_g09.verify_claim import build_receipt, digest, verify


class G09ClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(
            Path("fin_rvi_002_g09/claim_contract.json").read_text(encoding="utf-8")
        )

    def test_contract_is_valid_but_open(self) -> None:
        self.assertEqual(verify(self.contract), [])
        receipt = build_receipt(self.contract)
        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["status"], "OPEN")
        self.assertFalse(receipt["promotion_allowed"])
        self.assertEqual(receipt["passed_required_gates"], 1)

    def test_claim_cannot_expand_to_fraud(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["scope"]["excluded_claims"].remove("fraud")
        self.assertIn("excluded-claims", verify(altered))

    def test_absorbed_prior_art_cannot_be_reclaimed(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["prior_art_absorbed"].remove("public_payment_record_linkage")
        self.assertIn("prior-art-boundary", verify(altered))

    def test_premature_pass_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["status"] = "PASS"
        self.assertIn("premature-pass", verify(altered))

    def test_all_gates_allow_pass(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["status"] = "PASS"
        altered["current_gates"] = {
            gate: "PASS" for gate in altered["required_gates"]
        }
        self.assertEqual(verify(altered), [])
        self.assertTrue(build_receipt(altered)["promotion_allowed"])

    def test_digest_is_deterministic(self) -> None:
        self.assertEqual(digest(self.contract), digest(copy.deepcopy(self.contract)))


if __name__ == "__main__":
    unittest.main()
