from __future__ import annotations

import unittest

from .numeric_consensus_candidate_v4_wildreceipt import external_protocol
from .wildreceipt_external import (
    AGGREGATE_SCHEMA,
    ALPHA_PER_LEG,
    MINIMUM_ACCEPTED,
    MINIMUM_COVERAGE,
    MINIMUM_SELECTED,
    MINIMUM_STABILITY_PASS_FRACTION,
    TARGET_REDUCTION,
    exact_summary,
)


def observation(
    *,
    baseline_eligible: bool = True,
    baseline_correct: bool = True,
    accepted: bool = False,
    false_accept: bool = False,
    counterfactual_false: bool = False,
) -> dict:
    return {
        "baseline": {
            "eligible": baseline_eligible,
            "claim_correct": baseline_correct,
        },
        "candidate": {
            "accepted": accepted,
            "false_accept": false_accept,
        },
        "counterfactual": {
            "false_accept": counterfactual_false,
        },
    }


class WildReceiptExternalTests(unittest.TestCase):
    def test_frozen_certificate_constants_match_protocol(self) -> None:
        protocol = external_protocol()
        gates = protocol["exact_gates"]
        self.assertEqual(AGGREGATE_SCHEMA, "ocr-wildreceipt-numeric-aggregate/1")
        self.assertEqual(ALPHA_PER_LEG, 0.0125)
        self.assertEqual(TARGET_REDUCTION, 10.0)
        self.assertEqual(MINIMUM_SELECTED, 1200)
        self.assertEqual(MINIMUM_ACCEPTED, 400)
        self.assertEqual(MINIMUM_COVERAGE, 0.25)
        self.assertEqual(MINIMUM_STABILITY_PASS_FRACTION, 2.0 / 3.0)
        self.assertEqual(gates["target_error_reduction"], TARGET_REDUCTION)
        self.assertEqual(
            gates["minimum_selected_unique_receipts"], MINIMUM_SELECTED
        )
        self.assertEqual(gates["minimum_accepted"], MINIMUM_ACCEPTED)
        self.assertEqual(gates["minimum_coverage_lower"], MINIMUM_COVERAGE)

    def test_exact_summary_can_certify_zero_retained_errors(self) -> None:
        rows = []
        for index in range(1200):
            baseline_eligible = index < 800
            baseline_correct = not (baseline_eligible and index < 160)
            accepted = 160 <= index < 610
            rows.append(
                observation(
                    baseline_eligible=baseline_eligible,
                    baseline_correct=baseline_correct,
                    accepted=accepted,
                )
            )
        result = exact_summary(rows)
        self.assertEqual(result["selected"], 1200)
        self.assertEqual(result["baseline_eligible"], 800)
        self.assertEqual(result["baseline_false"], 160)
        self.assertEqual(result["accepted"], 450)
        self.assertEqual(result["accepted_false"], 0)
        self.assertEqual(result["counterfactual_false"], 0)
        self.assertGreaterEqual(result["coverage_lower"], MINIMUM_COVERAGE)
        self.assertGreaterEqual(result["reduction_lower"], TARGET_REDUCTION)
        self.assertTrue(result["pass"])

    def test_underpowered_denominator_fails_even_with_zero_errors(self) -> None:
        rows = [
            observation(
                baseline_eligible=True,
                baseline_correct=index >= 100,
                accepted=100 <= index < 450,
            )
            for index in range(1000)
        ]
        result = exact_summary(rows)
        self.assertEqual(result["selected"], 1000)
        self.assertFalse(result["pass"])

    def test_retained_false_accepts_fail_closed(self) -> None:
        rows = []
        for index in range(1200):
            baseline_eligible = index < 800
            baseline_correct = not (baseline_eligible and index < 160)
            accepted = 160 <= index < 610
            false_accept = index in {607, 608, 609}
            rows.append(
                observation(
                    baseline_eligible=baseline_eligible,
                    baseline_correct=baseline_correct,
                    accepted=accepted,
                    false_accept=false_accept,
                )
            )
        result = exact_summary(rows)
        self.assertEqual(result["accepted_false"], 3)
        self.assertFalse(result["pass"])

    def test_counterfactual_failure_fails_closed(self) -> None:
        rows = []
        for index in range(1200):
            baseline_eligible = index < 800
            baseline_correct = not (baseline_eligible and index < 160)
            accepted = 160 <= index < 610
            rows.append(
                observation(
                    baseline_eligible=baseline_eligible,
                    baseline_correct=baseline_correct,
                    accepted=accepted,
                    counterfactual_false=index < 20,
                )
            )
        result = exact_summary(rows)
        self.assertEqual(result["counterfactual_false"], 20)
        self.assertGreater(result["counterfactual_upper"], 0.01)
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
