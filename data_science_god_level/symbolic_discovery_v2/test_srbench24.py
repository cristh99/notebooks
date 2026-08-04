from __future__ import annotations

import unittest

import numpy as np

from srbench24_runner import (
    ALL_DATASETS,
    BLACKBOX_DATASETS,
    FIRST_PRINCIPLES_DATASETS,
    THRESHOLDS,
    adjudicate,
    clean_arrays,
    split_indices,
    stable_seed,
)


class SRBench24GateTests(unittest.TestCase):
    def test_dataset_contract_is_complete_and_disjoint(self) -> None:
        self.assertEqual(len(BLACKBOX_DATASETS), 12)
        self.assertEqual(len(FIRST_PRINCIPLES_DATASETS), 12)
        self.assertEqual(len(ALL_DATASETS), 24)
        self.assertEqual(len(set(ALL_DATASETS)), 24)
        self.assertTrue(set(BLACKBOX_DATASETS).isdisjoint(FIRST_PRINCIPLES_DATASETS))

    def test_split_is_deterministic_and_disjoint(self) -> None:
        train_a, test_a = split_indices(500, "example")
        train_b, test_b = split_indices(500, "example")
        np.testing.assert_array_equal(train_a, train_b)
        np.testing.assert_array_equal(test_a, test_b)
        self.assertTrue(set(train_a).isdisjoint(test_a))
        self.assertGreater(train_a.size, test_a.size)
        self.assertNotEqual(stable_seed("example"), stable_seed("different"))

    def test_relative_scale_keeps_tiny_varying_targets(self) -> None:
        rng = np.random.default_rng(7)
        X_train = rng.normal(size=(80, 4))
        X_test = rng.normal(size=(20, 4))
        y_train = 1e-30 * (1.0 + 0.25 * X_train[:, 0])
        y_test = 1e-30 * (1.0 + 0.25 * X_test[:, 0])
        cleaned = clean_arrays(X_train, X_test, y_train, y_test)
        self.assertEqual(cleaned[0].shape, (80, 4))
        self.assertGreater(float(np.std(cleaned[2])), 0.0)

    def test_gate_is_not_trivial(self) -> None:
        failing = {
            "task_count": 24,
            "candidate_failures": 0,
            "overall_median_r2": 0.64,
            "overall_worst_r2": -0.5,
            "blackbox_mean_r2": 0.5,
            "blackbox_median_r2": 0.6,
            "firstprinciples_median_r2": 0.95,
            "firstprinciples_high_fidelity": 8,
            "wins_vs_best": 5,
            "within_0_05_of_best": 12,
            "mean_gap_vs_best": -0.1,
            "median_term_count": 5.0,
            "total_runtime_seconds": 100.0,
            "finite_all": True,
        }
        checks, verdict = adjudicate(failing)
        self.assertEqual(verdict, "FAIL")
        self.assertFalse(checks["overall_median_r2"])
        passing = dict(failing)
        passing["overall_median_r2"] = float(THRESHOLDS["overall_median_r2_min"])
        checks, verdict = adjudicate(passing)
        self.assertEqual(verdict, "PASS")
        self.assertTrue(all(checks.values()))


if __name__ == "__main__":
    unittest.main()
