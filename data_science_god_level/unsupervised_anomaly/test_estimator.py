from __future__ import annotations

import unittest

import numpy as np
from sklearn.metrics import roc_auc_score

from estimator import score_anomalies


class EstimatorTests(unittest.TestCase):
    def test_detects_global_anomalies(self) -> None:
        rng = np.random.default_rng(3)
        normal = rng.normal(0.0, 1.0, size=(500, 8))
        anomalies = rng.normal(7.0, 0.4, size=(25, 8))
        X = np.vstack([normal, anomalies])
        y = np.r_[np.zeros(len(normal)), np.ones(len(anomalies))]
        result = score_anomalies(X, random_state=11)
        self.assertGreater(roc_auc_score(y, result.scores), 0.95)
        self.assertTrue(result.diagnostics["finite"])

    def test_detects_local_density_anomalies(self) -> None:
        rng = np.random.default_rng(5)
        left = rng.normal([-3.0, 0.0], [0.45, 0.45], size=(350, 2))
        right = rng.normal([3.0, 0.0], [0.45, 0.45], size=(350, 2))
        anomalies = rng.normal([0.0, 0.0], [0.12, 0.12], size=(20, 2))
        X = np.vstack([left, right, anomalies])
        y = np.r_[np.zeros(len(left) + len(right)), np.ones(len(anomalies))]
        result = score_anomalies(X, random_state=13)
        self.assertGreater(roc_auc_score(y, result.scores), 0.90)

    def test_handles_missing_and_high_dimensional_data(self) -> None:
        rng = np.random.default_rng(7)
        X = rng.normal(size=(240, 100))
        X[::17, 3] = np.nan
        X[::31, 11] = np.inf
        result = score_anomalies(X, random_state=17)
        self.assertEqual(result.scores.shape, (240,))
        self.assertTrue(np.isfinite(result.scores).all())
        self.assertEqual(
            result.diagnostics["distance_representation"],
            "whitened_pca",
        )

    def test_rejects_too_few_rows(self) -> None:
        with self.assertRaises(ValueError):
            score_anomalies(np.zeros((10, 2)))


if __name__ == "__main__":
    unittest.main()
