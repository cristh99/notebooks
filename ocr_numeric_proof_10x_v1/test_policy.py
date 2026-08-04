from __future__ import annotations

import unittest
from collections import Counter

from .policy import accepted_counter, multiset_metrics


class NumericProofPolicyTests(unittest.TestCase):
    def test_accepts_only_numbers_repeated_by_both_engines(self) -> None:
        first = Counter({"104729": 2, "7": 3, "99": 1})
        second = Counter({"104729": 3, "7": 1, "99": 2})
        accepted = accepted_counter(first, second, min_repeat=2)
        self.assertEqual(accepted, Counter({"104729": 2}))

    def test_accepted_multiplicity_is_minimum(self) -> None:
        accepted = accepted_counter(
            Counter({"2024": 5}),
            Counter({"2024": 3}),
            min_repeat=2,
        )
        self.assertEqual(accepted["2024"], 3)

    def test_invalid_repeat_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            accepted_counter(Counter(), Counter(), min_repeat=0)

    def test_false_acceptance_rate(self) -> None:
        metrics = multiset_metrics(
            Counter({"2024": 2, "7": 1}),
            Counter({"2024": 2, "8": 1}),
        )
        self.assertAlmostEqual(metrics["precision"], 2 / 3)
        self.assertAlmostEqual(
            metrics["false_acceptance_rate"],
            1 / 3,
        )


if __name__ == "__main__":
    unittest.main()
