from __future__ import annotations

import unittest

from .risk_certificate import (
    CertificateConfig,
    SelectiveRiskCounts,
    build_certificate,
)


class RiskCertificateTests(unittest.TestCase):
    def test_rejects_trivial_abstention(self) -> None:
        report = build_certificate(
            SelectiveRiskCounts(
                eligible_locations=1000,
                baseline_errors=150,
                accepted_locations=1,
                accepted_errors=0,
                counterfactual_accepts=0,
                counterfactual_trials=1000,
            )
        )
        self.assertFalse(report["gates"]["coverage_at_least_floor"])
        self.assertFalse(report["gates"]["pass"])

    def test_zero_observed_retained_errors_is_not_zero_risk(self) -> None:
        report = build_certificate(
            SelectiveRiskCounts(
                eligible_locations=1000,
                baseline_errors=200,
                accepted_locations=100,
                accepted_errors=0,
                counterfactual_accepts=0,
                counterfactual_trials=100,
            ),
            CertificateConfig(minimum_coverage=0.05),
        )
        self.assertGreater(
            report["simultaneous_bounds"]["retained_error_upper"],
            0.0,
        )

    def test_clear_pass_with_large_clean_accept_set(self) -> None:
        report = build_certificate(
            SelectiveRiskCounts(
                eligible_locations=5000,
                baseline_errors=1000,
                accepted_locations=2500,
                accepted_errors=2,
                counterfactual_accepts=0,
                counterfactual_trials=2500,
            )
        )
        self.assertTrue(report["gates"]["pass"])
        self.assertGreaterEqual(
            report["simultaneous_bounds"]["risk_reduction_lower"],
            10.0,
        )

    def test_counterfactual_fail_blocks_release(self) -> None:
        report = build_certificate(
            SelectiveRiskCounts(
                eligible_locations=5000,
                baseline_errors=1000,
                accepted_locations=2500,
                accepted_errors=0,
                counterfactual_accepts=50,
                counterfactual_trials=2500,
            )
        )
        self.assertFalse(
            report["gates"]["counterfactual_accept_risk_below_ceiling"]
        )
        self.assertFalse(report["gates"]["pass"])

    def test_invalid_counts_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            SelectiveRiskCounts(
                eligible_locations=5,
                baseline_errors=6,
                accepted_locations=1,
                accepted_errors=0,
            )


if __name__ == "__main__":
    unittest.main()
