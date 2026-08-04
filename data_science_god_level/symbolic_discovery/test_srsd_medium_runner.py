from __future__ import annotations

import pickle
from pathlib import Path
import tempfile
import unittest

import numpy as np

import srsd_medium_runner as runner


class MediumRunnerTests(unittest.TestCase):
    def test_dataset_partition_is_complete(self) -> None:
        self.assertEqual(len(runner.DATASET_IDS), 40)
        self.assertEqual(runner.ONE_DUMMY | runner.TWO_DUMMIES | runner.THREE_DUMMIES, set(runner.DATASET_IDS))
        self.assertFalse(runner.ONE_DUMMY & runner.TWO_DUMMIES)
        self.assertFalse(runner.ONE_DUMMY & runner.THREE_DUMMIES)
        self.assertFalse(runner.TWO_DUMMIES & runner.THREE_DUMMIES)

    def test_bonus_slugs(self) -> None:
        self.assertEqual(runner._slug("B8"), "bonus.8")
        self.assertEqual(runner._slug("B18"), "bonus.18")
        self.assertEqual(runner._slug("III.8.54"), "iii.8.54")

    def test_safe_pickle_symbol_extraction_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "symbols.pkl"
            path.write_bytes(pickle.dumps(("x5", "x1", "other", "x5")))
            self.assertEqual(runner._safe_symbol_indices(path), (1, 5))
            self.assertAlmostEqual(runner._variable_f1({1, 4}, {1, 5}), 0.5)
            values = np.array([1.0, 2.0, 4.0])
            self.assertAlmostEqual(runner._nrmse(values, values), 0.0)

    def test_gate_and_failure_policy_are_nontrivial(self) -> None:
        self.assertEqual(runner.THRESHOLDS["task_count"], 40)
        self.assertEqual(runner.THRESHOLDS["candidate_failures_max"], 0)
        self.assertGreaterEqual(runner.THRESHOLDS["usable_count_min"], 24)
        self.assertGreaterEqual(runner.THRESHOLDS["candidate_mean_variable_f1_min"], 0.70)
        self.assertGreater(runner.THRESHOLDS["mean_gap_vs_best_min"], -0.15)
        failure = runner._candidate_failure(ValueError("x"))
        self.assertEqual(failure["test_r2"], runner.FAILURE_R2)
        self.assertIn("ValueError", failure["error"])


if __name__ == "__main__":
    unittest.main()
