from __future__ import annotations

import unittest

from .selective_risk_certificate_v4 import (
    bonferroni_per_look_family_alpha,
    build_certificate,
    minimum_zero_residual_flags,
)


class SelectiveRiskCertificateV4Tests(unittest.TestCase):
    def test_joint_95pct_all_error_zero_residual_threshold_is_39(self) -> None:
        self.assertEqual(
            minimum_zero_residual_flags(baseline_error_fraction=1.0),
            39,
        )
        self.assertFalse(
            build_certificate(
                flagged_claims=38,
                baseline_errors=38,
                accepted_claims=38,
                final_errors=0,
            ).pass_10x
        )
        self.assertTrue(
            build_certificate(
                flagged_claims=39,
                baseline_errors=39,
                accepted_claims=39,
                final_errors=0,
            ).pass_10x
        )

    def test_lower_baseline_error_fraction_requires_more_flags(self) -> None:
        self.assertEqual(
            minimum_zero_residual_flags(baseline_error_fraction=0.8),
            54,
        )
        self.assertEqual(
            minimum_zero_residual_flags(baseline_error_fraction=0.5),
            92,
        )

    def test_one_retained_error_requires_at_least_58_all_error_flags(self) -> None:
        failing = build_certificate(
            flagged_claims=57,
            baseline_errors=57,
            accepted_claims=57,
            final_errors=1,
        )
        passing = build_certificate(
            flagged_claims=58,
            baseline_errors=58,
            accepted_claims=58,
            final_errors=1,
        )
        self.assertFalse(failing.pass_10x)
        self.assertLess(failing.certified_reduction_lower or 0.0, 10.0)
        self.assertTrue(passing.pass_10x)
        self.assertGreaterEqual(passing.certified_reduction_lower or 0.0, 10.0)

    def test_quarantine_is_explicit_and_not_counted_as_acceptance(self) -> None:
        certificate = build_certificate(
            flagged_claims=50,
            baseline_errors=50,
            accepted_claims=40,
            final_errors=0,
        )
        self.assertEqual(certificate.quarantined_claims, 10)
        self.assertEqual(certificate.accepted_claims, 40)

    def test_quarantine_coverage_increases_required_flag_count(self) -> None:
        full_coverage = minimum_zero_residual_flags(
            baseline_error_fraction=1.0, accepted_fraction=1.0
        )
        eighty_percent_coverage = minimum_zero_residual_flags(
            baseline_error_fraction=1.0, accepted_fraction=0.8
        )
        fifty_percent_coverage = minimum_zero_residual_flags(
            baseline_error_fraction=1.0, accepted_fraction=0.5
        )
        self.assertEqual(full_coverage, 39)
        self.assertGreater(eighty_percent_coverage, full_coverage)
        self.assertGreater(fifty_percent_coverage, eighty_percent_coverage)

    def test_invalid_planning_fractions_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            minimum_zero_residual_flags(baseline_error_fraction=0.0)
        with self.assertRaises(ValueError):
            minimum_zero_residual_flags(
                baseline_error_fraction=1.0, accepted_fraction=0.0
            )
        with self.assertRaises(ValueError):
            bonferroni_per_look_family_alpha(planned_looks=0)

    def test_three_look_plan_spends_alpha_and_raises_thresholds(self) -> None:
        per_look = bonferroni_per_look_family_alpha(
            overall_family_alpha=0.05, planned_looks=3
        )
        self.assertAlmostEqual(per_look, 0.05 / 3.0)
        self.assertEqual(
            minimum_zero_residual_flags(
                baseline_error_fraction=1.0,
                accepted_fraction=1.0,
                family_alpha=per_look,
            ),
            51,
        )
        self.assertEqual(
            minimum_zero_residual_flags(
                baseline_error_fraction=0.8,
                accepted_fraction=0.8,
                family_alpha=per_look,
            ),
            87,
        )
        self.assertEqual(
            minimum_zero_residual_flags(
                baseline_error_fraction=0.5,
                accepted_fraction=0.8,
                family_alpha=per_look,
            ),
            148,
        )

    def test_unadjusted_single_look_thresholds_do_not_pass_at_three_look_alpha(self) -> None:
        per_look = bonferroni_per_look_family_alpha(
            overall_family_alpha=0.05, planned_looks=3
        )
        for flagged, baseline_errors, accepted in (
            (39, 39, 39),
            (67, 53, 53),
            (114, 57, 91),
        ):
            self.assertFalse(
                build_certificate(
                    flagged_claims=flagged,
                    baseline_errors=baseline_errors,
                    accepted_claims=accepted,
                    final_errors=0,
                    family_alpha=per_look,
                ).pass_10x
            )

    def test_invalid_counts_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_certificate(
                flagged_claims=5,
                baseline_errors=6,
                accepted_claims=5,
                final_errors=0,
            )
        with self.assertRaises(ValueError):
            build_certificate(
                flagged_claims=5,
                baseline_errors=5,
                accepted_claims=4,
                final_errors=5,
            )

    def test_certificate_is_deterministic(self) -> None:
        first = build_certificate(
            flagged_claims=39,
            baseline_errors=39,
            accepted_claims=39,
            final_errors=0,
        )
        second = build_certificate(
            flagged_claims=39,
            baseline_errors=39,
            accepted_claims=39,
            final_errors=0,
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
