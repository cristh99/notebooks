from __future__ import annotations

import pickle
from pathlib import Path
import tempfile
import unittest

import numpy as np

import srsd_external_runner as runner


class ExternalRunnerTests(unittest.TestCase):
    def test_dataset_partition_is_complete(self) -> None:
        self.assertEqual(len(runner.DATASET_IDS), 30)
        self.assertEqual(
            runner.ONE_DUMMY | runner.TWO_DUMMIES | runner.THREE_DUMMIES,
            set(runner.DATASET_IDS),
        )
        self.assertFalse(runner.ONE_DUMMY & runner.TWO_DUMMIES)
        self.assertFalse(runner.ONE_DUMMY & runner.THREE_DUMMIES)
        self.assertFalse(runner.TWO_DUMMIES & runner.THREE_DUMMIES)

    def test_safe_pickle_symbol_extraction_does_not_unpickle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "symbols.pkl"
            path.write_bytes(pickle.dumps(("x7", "other", "x2", "x7")))
            self.assertEqual(runner._safe_symbol_indices(path), (2, 7))

    def test_load_table_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.txt"
            table = np.array([[1.0, 2.0, 5.0], [2.0, 3.0, 8.0], [3.0, 4.0, 11.0]])
            np.savetxt(path, table)
            X, y = runner._load_table(path)
            self.assertEqual(X.shape, (3, 2))
            np.testing.assert_allclose(y, [5.0, 8.0, 11.0])
            self.assertAlmostEqual(runner._nrmse(y, y), 0.0)
            self.assertAlmostEqual(runner._variable_f1({0, 2}, {0, 1}), 0.5)

    def test_gate_is_not_trivial(self) -> None:
        self.assertGreaterEqual(runner.THRESHOLDS["task_count"], 30)
        self.assertGreaterEqual(runner.THRESHOLDS["high_fidelity_count_min"], 10)
        self.assertGreaterEqual(runner.THRESHOLDS["usable_count_min"], 20)
        self.assertGreaterEqual(runner.THRESHOLDS["candidate_mean_variable_f1_min"], 0.75)
        self.assertLessEqual(runner.THRESHOLDS["mean_gap_vs_best_min"], 0.0)
        self.assertGreater(runner.THRESHOLDS["mean_gap_vs_best_min"], -0.10)


if __name__ == "__main__":
    unittest.main()
