from __future__ import annotations

import unittest

import numpy as np
from sklearn.datasets import load_breast_cancer, load_diabetes, make_classification
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import train_test_split

from estimator import fit_predict


class EstimatorTests(unittest.TestCase):
    def test_binary_classification(self):
        x, y = load_breast_cancer(return_X_y=True)
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=0.25, random_state=41, stratify=y
        )
        result = fit_predict(x_train, y_train, x_test, "classification")
        self.assertGreater(balanced_accuracy_score(y_test, result.predictions), 0.90)
        self.assertEqual(result.probabilities.shape, (len(x_test), 2))

    def test_multiclass_and_missing_values(self):
        x, y = make_classification(
            n_samples=600,
            n_features=18,
            n_informative=12,
            n_classes=3,
            random_state=7,
        )
        x[::31, 2] = np.nan
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=0.25, random_state=43, stratify=y
        )
        result = fit_predict(x_train, y_train, x_test, "classification")
        self.assertGreater(balanced_accuracy_score(y_test, result.predictions), 0.70)
        self.assertTrue(np.isfinite(result.probabilities).all())

    def test_regression(self):
        x, y = load_diabetes(return_X_y=True)
        x_train, x_test, y_train, _ = train_test_split(
            x, y, test_size=0.25, random_state=47
        )
        result = fit_predict(x_train, y_train, x_test, "regression")
        self.assertEqual(result.probabilities, None)
        self.assertTrue(np.isfinite(result.predictions).all())
        self.assertEqual(len(result.predictions), len(x_test))

    def test_rejects_shape_mismatch(self):
        with self.assertRaises(ValueError):
            fit_predict(np.ones((10, 3)), np.ones(10), np.ones((2, 4)), "regression")


if __name__ == "__main__":
    unittest.main()
