from __future__ import annotations

import unittest

from .postseal_evaluate_v4_2 import match_truth, numeric_truth


class PostSealEvaluatorV42Tests(unittest.TestCase):
    def test_amount_with_tax_code_is_parsed(self) -> None:
        self.assertEqual(numeric_truth("30.00 SR"), "3000")
        self.assertEqual(numeric_truth("144.68 *"), "14468")
        self.assertEqual(numeric_truth("RM 15.00"), "1500")
        self.assertEqual(numeric_truth("20.00 SR"), "2000")
        self.assertEqual(numeric_truth("2.60"), "260")
        self.assertEqual(numeric_truth("0.20 ZRL"), "020")

    def test_dates_and_non_amounts_are_rejected(self) -> None:
        self.assertIsNone(numeric_truth("20-06-2018"))
        self.assertIsNone(numeric_truth("SR"))
        self.assertIsNone(numeric_truth("2018"))

    def test_geometry_selects_covering_truth(self) -> None:
        truths = [
            {"line": 20, "text": "30.00 SR", "truth": "3000", "bbox": [526, 827, 650, 867]},
            {"line": 31, "text": "38.00", "truth": "3800", "bbox": [610, 1091, 695, 1127]},
        ]
        match = match_truth([618, 1098, 691, 1123], truths)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match[0]["truth"], "3800")
        self.assertEqual(match[0]["line"], 31)


if __name__ == "__main__":
    unittest.main()
