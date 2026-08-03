from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from fin_rvi_002_g09.verify_final_contract_v3 import build_receipt, verify


class FinalG09ContractV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = Path("fin_rvi_002_g09/final_contract_v2.json")
        cls.contract = json.loads(cls.path.read_text(encoding="utf-8"))

    def test_open_contract_is_valid_and_cannot_promote(self) -> None:
        self.assertEqual(verify(self.contract, Path(".")), [])
        receipt = build_receipt(self.contract, Path("."))
        payload = receipt["payload"]
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["promotion_allowed"])
        self.assertEqual(
            payload["gate_readout"],
            {"G07": "PASS", "G09": "OPEN", "finance_score": 920},
        )

    def test_premature_pass_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["status"] = "PASS"
        altered["gate_readout"] = {
            "G07": "PASS",
            "G09": "PASS",
            "finance_score": 1000,
        }
        errors = verify(altered, Path("."))
        self.assertIn("premature-pass", errors)
        self.assertIn("stage6-missing", errors)
        self.assertIn("stage7-missing", errors)

    def test_scope_expansion_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["scope"]["excluded_claims"].remove("fraud")
        self.assertIn("excluded-claims", verify(altered, Path(".")))

    def test_universal_claim_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["claim"] += " This is universal."
        self.assertIn("claim-expansion", verify(altered, Path(".")))

    def test_stage4_result_forgery_is_rejected(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["empirical_evidence"]["stage4"]["challenger"][
            "unsafe_overpromotions"
        ] = 1
        self.assertIn("stage4-challenger", verify(altered, Path(".")))

    def test_prior_art_absorption_cannot_be_removed(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["prior_art_boundary"]["absorbed_components"].pop()
        self.assertIn("prior-art-absorbed", verify(altered, Path(".")))

    def test_open_contract_cannot_claim_score_1000(self) -> None:
        altered = copy.deepcopy(self.contract)
        altered["gate_readout"]["finance_score"] = 1000
        self.assertIn("premature-score", verify(altered, Path(".")))


if __name__ == "__main__":
    unittest.main()
