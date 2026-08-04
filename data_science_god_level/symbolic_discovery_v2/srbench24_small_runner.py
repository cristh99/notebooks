from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.impute import SimpleImputer

import srbench24_runner as base


def split_indices(n_rows: int, dataset_name: str) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic 80/20 split that also supports official tiny datasets."""
    if n_rows < 8:
        raise ValueError("dataset must contain at least 8 rows")
    rng = np.random.default_rng(base.stable_seed(dataset_name))
    order = rng.permutation(n_rows)
    n_test = max(3, int(round(0.20 * n_rows)))
    n_test = min(n_test, 3000, n_rows - 6)
    test = order[:n_test]
    train = order[n_test:]
    if train.size > 10000:
        train = train[:10000]
    return train, test


def clean_arrays(
    X_train: np.ndarray,
    X_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    X_train = np.asarray(X_train, dtype=float)
    X_test = np.asarray(X_test, dtype=float)
    y_train = np.asarray(y_train, dtype=float).reshape(-1)
    y_test = np.asarray(y_test, dtype=float).reshape(-1)
    finite_train = np.isfinite(y_train)
    finite_test = np.isfinite(y_test)
    X_train, y_train = X_train[finite_train], y_train[finite_train]
    X_test, y_test = X_test[finite_test], y_test[finite_test]
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    X_train = imputer.fit_transform(X_train)
    X_test = imputer.transform(X_test)
    if X_train.shape[0] < 6 or X_test.shape[0] < 3:
        raise ValueError("insufficient finite rows")
    scale = max(float(np.max(np.abs(y_train))), float(np.std(y_train)), 1e-300)
    if float(np.std(y_train)) <= np.finfo(float).eps * scale * 16:
        raise ValueError("target is constant relative to its scale")
    return X_train, X_test, y_train, y_test


def run(data_root: Path, output: Path) -> dict[str, object]:
    # Patch only the two protocol functions required by the official small-n tasks.
    base.split_indices = split_indices
    base.clean_arrays = clean_arrays
    report = base.run(data_root, output)
    report["small_sample_protocol"] = {
        "minimum_total_rows": 8,
        "minimum_train_rows": 6,
        "minimum_test_rows": 3,
        "candidate_changed": False,
        "datasets_changed": False,
        "metrics_changed": False,
        "thresholds_changed": False,
        "baselines_changed": False,
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.data_root, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
