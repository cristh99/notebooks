from __future__ import annotations

import unittest

from . import benchmark as base
from .balanced import (
    PP_THREAD_BUDGET,
    TESSERACT_THREAD_BUDGET,
    decision_from,
)


def synthetic_report() -> dict:
    return {
        "evaluation": {
            "policy": {
                "precision": 0.99,
                "reference_coverage": 0.40,
                "prediction_count": 350,
            },
            "false_acceptance_error_reduction_factor": 12.0,
        },
        "leave_one_page_out": {"passes": 19},
        "parity": {
            "isolated_parallel_text_hashes_equal": True,
            "tesseract_vs_frozen_speed_frontier": {"f1": 0.98},
            "pp_1024_vs_frozen_speed_frontier": {"f1": 0.90},
        },
        "runtime": {
            "pair_ratio_to_tesseract": 1.05,
            "mean_extra_wall_seconds_per_page": 0.10,
            "p90_page_extra_wall_seconds": 0.25,
        },
    }


class BalancedParallelTests(unittest.TestCase):
    def test_asymmetric_budgets_protect_primary_engine(self) -> None:
        self.assertEqual(TESSERACT_THREAD_BUDGET, 10)
        self.assertEqual(PP_THREAD_BUDGET, 1)
        self.assertLess(PP_THREAD_BUDGET, TESSERACT_THREAD_BUDGET)

    def test_old_output_drift_is_diagnostic_not_blocking(self) -> None:
        decision = decision_from(synthetic_report())
        self.assertTrue(decision["frozen_drift_detected"])
        self.assertTrue(decision["concurrency_parity_gate"])
        self.assertTrue(decision["runtime_gate"])
        self.assertTrue(decision["promotion_gate"])

    def test_concurrency_output_change_fails_closed(self) -> None:
        report = synthetic_report()
        report["parity"]["isolated_parallel_text_hashes_equal"] = False
        decision = decision_from(report)
        self.assertFalse(decision["concurrency_parity_gate"])
        self.assertFalse(decision["runtime_gate"])
        self.assertFalse(decision["promotion_gate"])

    def test_overhead_gate_is_not_weakened(self) -> None:
        report = synthetic_report()
        report["runtime"]["pair_ratio_to_tesseract"] = (
            base.MAX_PAIR_RATIO + 0.001
        )
        decision = decision_from(report)
        self.assertFalse(decision["runtime_gate"])
        self.assertFalse(decision["promotion_gate"])

    def test_quality_gate_is_not_weakened(self) -> None:
        report = synthetic_report()
        report["evaluation"]["false_acceptance_error_reduction_factor"] = 9.99
        decision = decision_from(report)
        self.assertFalse(decision["quality_gate"])
        self.assertFalse(decision["promotion_gate"])


if __name__ == "__main__":
    unittest.main()
