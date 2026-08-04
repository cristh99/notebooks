from __future__ import annotations

import unittest

from .risk_certificate import CertificateConfig, build_certificate
from .sample_size_plan import (
    PlanningScenario,
    counts_for_size,
    minimum_size,
)


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

    def test_equal_assumed_and_required_coverage_is_finitely_impossible(self) -> None:
        result = minimum_size(
            PlanningScenario(0.20, 0.25, 0),
            CertificateConfig(minimum_coverage=0.25),
        )
        self.assertFalse(result["passes"])
        self.assertIsNone(result["minimum_size"])
        self.assertEqual(
            result["reason"],
            "FINITE_COVERAGE_BOUND_IMPOSSIBLE",
        )
        self.assertEqual(result["evaluated_sizes"], 0)

    def test_returns_the_exact_first_passing_integer(self) -> None:
        scenario = PlanningScenario(0.15, 0.50, 1)
        config = CertificateConfig(
            minimum_coverage=0.20,
            require_counterfactual_gate=False,
        )
        result = minimum_size(
            scenario,
            config,
            maximum=20_000,
        )
        self.assertTrue(result["passes"])
        size = int(result["minimum_size"])
        self.assertTrue(
            build_certificate(
                counts_for_size(size, scenario),
                config,
            )["gates"]["pass"]
        )
        self.assertFalse(
            build_certificate(
                counts_for_size(size - 1, scenario),
                config,
            )["gates"]["pass"]
        )

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
