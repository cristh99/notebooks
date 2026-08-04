from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from .model import (
    bank_cluster_bootstrap,
    calibration_error,
    cost_at_threshold,
    fit_transform_state,
    select_threshold,
    transform,
)
from .panel import FEATURE_COLUMNS


class FdicModelTests(unittest.TestCase):
    def feature_frame(self) -> pd.DataFrame:
        rows = []
        for index in range(20):
            row = {column: float(index + 1) for column in FEATURE_COLUMNS}
            row["equity_assets"] = np.nan if index % 3 == 0 else 0.1 + index / 1000
            rows.append(row)
        return pd.DataFrame(rows)

    def test_train_only_transform_is_finite_and_deterministic(self) -> None:
        frame = self.feature_frame()
        state = fit_transform_state(frame)
        first = transform(frame, state)
        second = transform(frame, state)
        self.assertEqual(first.columns.tolist(), list(state.output_columns))
        self.assertTrue(np.isfinite(first.to_numpy(dtype=float)).all())
        np.testing.assert_allclose(first, second)

    def test_cost_function_uses_declared_loss_ratio(self) -> None:
        labels = np.array([1, 1, 0, 0], dtype=int)
        probabilities = np.array([0.9, 0.2, 0.8, 0.1])
        cost = cost_at_threshold(labels, probabilities, 0.5)
        self.assertEqual(cost["false_negatives"], 1)
        self.assertEqual(cost["false_positives"], 1)
        self.assertEqual(cost["total_cost"], 101.0)

    def test_threshold_selection_is_deterministic(self) -> None:
        labels = np.array([1, 1, 0, 0, 0], dtype=int)
        probabilities = np.array([0.9, 0.4, 0.8, 0.2, 0.1])
        self.assertEqual(
            select_threshold(labels, probabilities),
            select_threshold(labels, probabilities),
        )

    def test_calibration_error_is_zero_for_perfect_bins(self) -> None:
        labels = np.array([0, 0, 1, 1], dtype=int)
        probabilities = np.array([0.0, 0.0, 1.0, 1.0])
        self.assertAlmostEqual(calibration_error(labels, probabilities), 0.0)

    def test_bank_cluster_bootstrap_is_deterministic(self) -> None:
        frame = pd.DataFrame(
            {
                "CERT": [1, 1, 2, 2, 3, 3],
                "label": [1, 0, 1, 0, 1, 0],
            }
        )
        baseline = np.array([0.1, 0.9, 0.1, 0.9, 0.1, 0.9])
        challenger = np.array([0.9, 0.1, 0.9, 0.1, 0.9, 0.1])
        first = bank_cluster_bootstrap(
            frame, baseline, challenger, 0.5, 0.5, replicates=100
        )
        second = bank_cluster_bootstrap(
            frame, baseline, challenger, 0.5, 0.5, replicates=100
        )
        self.assertEqual(first, second)
        self.assertGreater(first["lower_95"], 0)


if __name__ == "__main__":
    unittest.main()
