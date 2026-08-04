from __future__ import annotations

import unittest

from .risk_certificate import CertificateConfig
from .sample_size_plan import PlanningScenario, counts_for_size, minimum_size


class SampleSizePlanTests(unittest.TestCase):
    def test_counts_are_valid(self) -> None:
        counts = counts_for_size(
            1000,
            PlanningScenario(0.10, 0.50, 1),
        )
        self.assertEqual(counts.eligible_locations, 1000)
        self.assertEqual(counts.baseline_errors, 100)
        self.assertEqual(counts.accepted_locations, 500)
        self.assertEqual(counts.accepted_errors, 1)

    def test_harder_error_profile_requires_no_smaller_sample(self) -> None:
        config = CertificateConfig(
            minimum_coverage=0.20,
            require_counterfactual_gate=False,
        )
        clean = minimum_size(
            PlanningScenario(0.15, 0.50, 0),
            config,
            maximum=20_000,
        )
        one_error = minimum_size(
            PlanningScenario(0.15, 0.50, 1),
            config,
            maximum=20_000,
        )
        self.assertTrue(clean["passes"])
        self.assertTrue(one_error["passes"])
        self.assertGreaterEqual(
            int(one_error["minimum_size"]),
            int(clean["minimum_size"]),
        )

    def test_lower_baseline_error_is_not_easier(self) -> None:
        config = CertificateConfig(
            minimum_coverage=0.20,
            require_counterfactual_gate=False,
        )
        low = minimum_size(
            PlanningScenario(0.05, 0.50, 0),
            config,
            maximum=30_000,
        )
        high = minimum_size(
            PlanningScenario(0.20, 0.50, 0),
            config,
            maximum=30_000,
        )
        self.assertTrue(low["passes"])
        self.assertTrue(high["passes"])
        self.assertGreaterEqual(
            int(low["minimum_size"]),
            int(high["minimum_size"]),
        )


if __name__ == "__main__":
    unittest.main()
