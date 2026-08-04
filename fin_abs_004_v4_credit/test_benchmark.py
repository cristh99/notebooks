from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from .benchmark import (
    ABSOLUTE_SCORE_BEFORE,
    Encoder,
    apply_platt,
    best_f1_threshold,
    build_fold_assignments,
    company_cluster_ci,
    fit_platt,
    metrics,
    select_weight,
    split_indices,
)


class CreditCalibrationTests(unittest.TestCase):
    def test_grouped_folds_keep_company_together(self) -> None:
        frame = pd.DataFrame(
            {
                "country": ["A"] * 6 + ["B"] * 6,
                "company": ["x", "x", "y", "y", "z", "z"] * 2,
            }
        )
        folds = build_fold_assignments(frame)
        for (_, _company), sub in frame.assign(fold=folds).groupby(["country", "company"]):
            self.assertEqual(sub["fold"].nunique(), 1)

    def test_split_has_zero_overlap(self) -> None:
        frame = pd.DataFrame(
            {
                "country": ["A"] * 20,
                "company": [f"c{i // 2}" for i in range(20)],
            }
        )
        folds = build_fold_assignments(frame)
        train, val, test = split_indices(folds, 0)
        groups = frame["company"].to_numpy()
        self.assertFalse(set(groups[train]) & set(groups[val]))
        self.assertFalse(set(groups[train]) & set(groups[test]))
        self.assertFalse(set(groups[val]) & set(groups[test]))

    def test_encoder_uses_train_categories_and_medians(self) -> None:
        train = pd.DataFrame({"x": [1.0, np.nan, 3.0], "c": ["a", "b", None]})
        test = pd.DataFrame({"x": [np.nan], "c": ["new"]})
        encoder = Encoder().fit(train)
        values = encoder.transform(test)
        self.assertAlmostEqual(float(values[0, 0]), 2.0)
        self.assertEqual(float(values[0, 1]), -1.0)

    def test_platt_is_monotone(self) -> None:
        y = np.array([0, 0, 0, 1, 1, 1], dtype=np.int8)
        p = np.array([0.01, 0.05, 0.2, 0.4, 0.7, 0.95], dtype=float)
        model = fit_platt(y, p)
        calibrated = apply_platt(model, p)
        self.assertTrue(np.all(np.diff(calibrated) > 0))

    def test_weight_selection_prefers_lower_brier(self) -> None:
        y = np.array([0, 0, 1, 1], dtype=np.int8)
        good = np.array([0.01, 0.1, 0.8, 0.95])
        bad = np.array([0.4, 0.4, 0.6, 0.6])
        weight, _ = select_weight(y, good, bad)
        self.assertEqual(weight, 1.0)

    def test_metrics_and_threshold_are_finite(self) -> None:
        y = np.array([0, 0, 0, 1, 1], dtype=np.int8)
        p = np.array([0.01, 0.05, 0.2, 0.6, 0.9])
        threshold = best_f1_threshold(y, p)
        result = metrics(y, p, threshold)
        self.assertGreater(result["roc_auc"], 0.9)
        self.assertGreater(result["average_precision"], 0.9)
        self.assertGreaterEqual(result["ece_20"], 0.0)

    def test_cluster_ci_detects_uniform_gain(self) -> None:
        company = np.array(["a", "a", "b", "b"])
        y = np.array([0, 1, 0, 1], dtype=float)
        baseline = np.array([0.4, 0.6, 0.4, 0.6])
        challenger = np.array([0.1, 0.9, 0.1, 0.9])
        result = company_cluster_ci(
            company,
            baseline,
            challenger,
            y,
            maximum_companies=10,
            repetitions=100,
        )
        self.assertGreater(result["ci95"][0], 0.0)

    def test_absolute_score_constant_is_conservative(self) -> None:
        self.assertEqual(ABSOLUTE_SCORE_BEFORE, 423)


if __name__ == "__main__":
    unittest.main()
