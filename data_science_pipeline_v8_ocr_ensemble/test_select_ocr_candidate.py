from __future__ import annotations

import unittest
from decimal import Decimal

from select_ocr_candidate import bounded_word_term, choose_candidate, score_candidate


class CandidateSelectorTests(unittest.TestCase):
    def test_bounded_word_term_is_parameter_free_and_below_one(self) -> None:
        self.assertEqual(bounded_word_term(0), Decimal(0))
        self.assertEqual(bounded_word_term(1), Decimal("0.5"))
        self.assertLess(bounded_word_term(10_000_000), Decimal(1))

    def test_exact_score_formula(self) -> None:
        expected = Decimal("70") + Decimal(20) * Decimal("0.75") + Decimal(99) / Decimal(100)
        self.assertEqual(score_candidate(70.0, 0.75, 99), expected)

    def test_highest_eligible_score_wins(self) -> None:
        selected = choose_candidate([
            {"candidate_name": "balanced_200_psm6", "eligible": True, "score": "80.0"},
            {"candidate_name": "sparse_300_psm11", "eligible": True, "score": "81.0"},
            {"candidate_name": "auto_300_psm3", "eligible": False, "score": "99.0"},
        ])
        self.assertEqual(selected["candidate_name"], "sparse_300_psm11")

    def test_lexical_tie_break_is_stable(self) -> None:
        selected = choose_candidate([
            {"candidate_name": "sparse_300_psm11", "eligible": True, "score": "81.0"},
            {"candidate_name": "auto_300_psm3", "eligible": True, "score": "81.0"},
            {"candidate_name": "balanced_200_psm6", "eligible": True, "score": "81.0"},
        ])
        self.assertEqual(selected["candidate_name"], "auto_300_psm3")

    def test_no_eligible_candidate_fails_closed(self) -> None:
        self.assertIsNone(choose_candidate([
            {"candidate_name": "auto_300_psm3", "eligible": False, "score": "90.0"},
        ]))


if __name__ == "__main__":
    unittest.main()
