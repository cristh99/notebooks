from __future__ import annotations

import gzip
import io
import unittest

import numpy as np
import pandas as pd

from srbench24_data import DATA_COMMIT, dataset_url, parse_dataset
from srbench24_runner import (
    ALL_DATASETS,
    BLACKBOX_DATASETS,
    FIRST_PRINCIPLES_DATASETS,
    THRESHOLDS,
    adjudicate,
    stable_seed,
)
from srbench24_small_runner import clean_arrays, split_indices


class SRBench24GateTests(unittest.TestCase):
    def test_dataset_contract_is_complete_and_disjoint(self) -> None:
        self.assertEqual(len(BLACKBOX_DATASETS), 12)
        self.assertEqual(len(FIRST_PRINCIPLES_DATASETS), 12)
        self.assertEqual(len(ALL_DATASETS), 24)
        self.assertEqual(len(set(ALL_DATASETS)), 24)
        self.assertTrue(set(BLACKBOX_DATASETS).isdisjoint(FIRST_PRINCIPLES_DATASETS))

    def test_pinned_media_url_and_parser(self) -> None:
        url = dataset_url("1028_SWD")
        self.assertIn(DATA_COMMIT, url)
        self.assertIn("media.githubusercontent.com/media/EpistasisLab/pmlb", url)
        self.assertTrue(url.endswith("/datasets/1028_SWD/1028_SWD.tsv.gz"))
        frame = pd.DataFrame(
            {
                "x0": [1.0, 2.0, 3.0],
                "x1": [4.0, 5.0, 6.0],
                "target": [7.0, 8.0, 9.0],
            }
        )
        raw = io.BytesIO()
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as stream:
            stream.write(frame.to_csv(sep="\t", index=False).encode("utf-8"))
        X, y, columns = parse_dataset(raw.getvalue(), "synthetic")
        self.assertEqual(columns, ["x0", "x1"])
        np.testing.assert_allclose(X, frame[["x0", "x1"]].to_numpy())
        np.testing.assert_allclose(y, frame["target"].to_numpy())

    def test_split_matches_srbench_75_25_and_is_deterministic(self) -> None:
        train_a, test_a = split_indices(500, "example")
        train_b, test_b = split_indices(500, "example")
        np.testing.assert_array_equal(train_a, train_b)
        np.testing.assert_array_equal(test_a, test_b)
        self.assertTrue(set(train_a).isdisjoint(test_a))
        self.assertEqual(train_a.size, 375)
        self.assertEqual(test_a.size, 125)
        self.assertNotEqual(stable_seed("example"), stable_seed("different"))

    def test_official_six_row_split_is_supported(self) -> None:
        train, test = split_indices(6, "first_principles_kepler")
        self.assertEqual(train.size, 4)
        self.assertEqual(test.size, 2)
        self.assertTrue(set(train).isdisjoint(test))
        X = np.arange(12, dtype=float).reshape(6, 2)
        y = np.linspace(1.0, 2.0, 6)
        cleaned = clean_arrays(X[train], X[test], y[train], y[test])
        self.assertEqual(cleaned[0].shape[0], 4)
        self.assertEqual(cleaned[1].shape[0], 2)

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
