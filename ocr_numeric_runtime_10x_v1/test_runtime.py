from __future__ import annotations

import unittest
from collections import Counter

from .runtime import (
    accepted_from_candidates,
    clamp_box,
    evaluate_pages,
    stable_payload,
)


class RuntimeNumericProofTests(unittest.TestCase):
    def test_accepts_two_independent_agreements(self) -> None:
        candidates = [
            {"baseline_token": "25", "paddle_token": "25"},
            {"baseline_token": "25", "paddle_token": "25"},
            {"baseline_token": "25", "paddle_token": "24"},
        ]
        self.assertEqual(
            accepted_from_candidates(candidates),
            Counter({"25": 2}),
        )

    def test_single_agreement_fails_closed(self) -> None:
        candidates = [
            {"baseline_token": "25", "paddle_token": "25"},
            {"baseline_token": "25", "paddle_token": "24"},
        ]
        self.assertEqual(accepted_from_candidates(candidates), Counter())

    def test_unrepeated_number_never_enters_channel(self) -> None:
        candidates = [{"baseline_token": "2011", "paddle_token": "2011"}]
        self.assertEqual(accepted_from_candidates(candidates), Counter())

    def test_evaluation_measures_false_acceptance_not_abstention_as_error(self) -> None:
        pages = [
            {
                "page_id": "p1",
                "reference_tokens": ["1"] * 20,
                "baseline_tokens": ["1"] * 20 + ["9"] * 10,
                "accepted_tokens": ["1"] * 10,
            }
        ]
        result = evaluate_pages(pages)
        self.assertAlmostEqual(result["baseline"]["precision"], 2 / 3)
        self.assertEqual(result["policy"]["precision"], 1.0)
        self.assertIsNone(
            result["false_acceptance_error_reduction_factor"]
        )

    def test_clamp_box_is_nonempty(self) -> None:
        self.assertEqual(clamp_box((-5, -2, 200, 100), 50, 40), (0, 0, 50, 40))

    def test_stable_payload_ignores_environment_and_digest(self) -> None:
        report = {
            "schema": "x",
            "value": 3,
            "environment": {"host": "a"},
            "stable_payload_sha256": "bad",
        }
        self.assertEqual(stable_payload(report), {"schema": "x", "value": 3})


if __name__ == "__main__":
    unittest.main()
