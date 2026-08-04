from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from fin_abs_004_fdic.panel import FEATURE_COLUMNS

from .model import (
    BASELINES,
    CHALLENGERS,
    entity_calibration_bucket,
    fit_calibrators,
    predict,
    random_forest_model,
    split_validation_entities,
    train_models,
)


def synthetic_frame(rows: int, *, start_cert: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(20260804 + start_cert)
    certs = np.arange(start_cert, start_cert + rows) // 4
    labels = ((certs % 9) == 0).astype(int)
    frame = pd.DataFrame(
        {
            column: rng.normal(labels * 0.7, 1.0, size=rows)
            for column in FEATURE_COLUMNS
        }
    )
    frame["CERT"] = certs
    frame["label"] = labels
    frame["days_to_failure"] = np.where(
        labels == 1, rng.integers(30, 730, size=rows), np.nan
    )
    return frame


def balanced_validation_rows(per_cell: int = 8) -> list[dict[str, float | int]]:
    counts = {
        ("calibration", 0): 0,
        ("calibration", 1): 0,
        ("selection", 0): 0,
        ("selection", 1): 0,
    }
    rows: list[dict[str, float | int]] = []
    cert = 20000
    while min(counts.values()) < per_cell:
        subset = "calibration" if entity_calibration_bucket(cert) < 50 else "selection"
        label = 1 if counts[(subset, 1)] < per_cell else 0
        if counts[(subset, label)] < per_cell:
            row: dict[str, float | int] = {
                column: float(label) for column in FEATURE_COLUMNS
            }
            row.update(
                {
                    "CERT": cert,
                    "label": label,
                    "days_to_failure": 365.0 if label else np.nan,
                }
            )
            rows.append(row)
            counts[(subset, label)] += 1
        cert += 1
    return rows


class FdicRandomForestModelTests(unittest.TestCase):
    def test_calibration_split_is_entity_disjoint_and_deterministic(self) -> None:
        validation = pd.DataFrame(balanced_validation_rows())
        first_cal, first_sel, first_report = split_validation_entities(validation)
        second_cal, second_sel, second_report = split_validation_entities(validation)
        self.assertEqual(first_report, second_report)
        self.assertEqual(set(first_cal["CERT"]), set(second_cal["CERT"]))
        self.assertEqual(set(first_sel["CERT"]), set(second_sel["CERT"]))
        self.assertFalse(set(first_cal["CERT"]) & set(first_sel["CERT"]))
        self.assertGreaterEqual(first_report["calibration_positive_entities"], 5)
        self.assertGreaterEqual(first_report["selection_positive_entities"], 5)
        self.assertEqual(set(first_cal["label"]), {0, 1})
        self.assertEqual(set(first_sel["label"]), {0, 1})

    def test_random_forest_probability_is_finite(self) -> None:
        rng = np.random.default_rng(17)
        x = rng.normal(size=(200, 8))
        y = np.array([0] * 180 + [1] * 20)
        model = random_forest_model(cost_sensitive=True, n_estimators=12)
        model.fit(x, y)
        probabilities = model.predict_proba(x)[:, 1]
        self.assertTrue(np.isfinite(probabilities).all())
        self.assertTrue(((probabilities >= 0) & (probabilities <= 1)).all())

    def test_full_family_trains_calibrates_and_predicts(self) -> None:
        train = synthetic_frame(480, start_cert=1000)
        validation = pd.DataFrame(balanced_validation_rows())
        calibration, selection, _ = split_validation_entities(validation)
        bundle = train_models(train, rf_trees=10)
        bundle = fit_calibrators(bundle, calibration)
        predictions = predict(bundle, selection)
        self.assertEqual(set(predictions), set((*BASELINES, *CHALLENGERS)))
        for values in predictions.values():
            self.assertEqual(len(values), len(selection))
            self.assertTrue(np.isfinite(values).all())
            self.assertTrue(((values >= 0) & (values <= 1)).all())


if __name__ == "__main__":
    unittest.main()
