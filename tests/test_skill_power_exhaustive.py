from __future__ import annotations

import unittest

from skill_power_canary.exhaustive import run_exhaustive


class ExhaustiveFiniteGrammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_exhaustive()

    def test_exhaustive_extension_passes(self) -> None:
        self.assertEqual(self.summary["outcome"], "PASS")
        self.assertEqual(self.summary["mismatch_count"], 0)
        self.assertEqual(self.summary["mismatches"], [])

    def test_declared_case_counts_are_stable(self) -> None:
        self.assertEqual(
            self.summary["counts"],
            {
                "claims": 14,
                "logic": 13825,
                "portfolio": 285,
                "secrets": 1024,
                "total": 15148,
                "maximum_privilege": 640,
            },
        )

    def test_exhaustive_summary_is_deterministic(self) -> None:
        second = run_exhaustive()
        self.assertEqual(second, self.summary)
        self.assertEqual(second["digest"], self.summary["digest"])

    def test_zero_spend_and_zero_network_contract(self) -> None:
        self.assertEqual(self.summary["external_spend_usd"], 0)
        self.assertEqual(self.summary["network_calls"], 0)

    def test_claim_boundary_remains_finite(self) -> None:
        boundary = self.summary["claim_boundary"]
        self.assertIn("finite grammars", boundary)
        self.assertIn("not hidden", boundary)
        self.assertIn("not", boundary)


if __name__ == "__main__":
    unittest.main()
