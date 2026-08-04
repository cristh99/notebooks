from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

BLACKBOX_DATASETS = (
    "1028_SWD",
    "1089_USCrime",
    "1193_BNG_lowbwt",
    "1199_BNG_echoMonths",
    "192_vineyard",
    "210_cloud",
    "522_pm10",
    "557_analcatdata_apnea1",
    "579_fri_c0_250_5",
    "606_fri_c2_1000_10",
    "650_fri_c0_500_50",
    "678_visualizing_environmental",
)
FIRST_PRINCIPLES_DATASETS = (
    "first_principles_absorption",
    "first_principles_bode",
    "first_principles_hubble",
    "first_principles_ideal_gas",
    "first_principles_kepler",
    "first_principles_leavitt",
    "first_principles_newton",
    "first_principles_planck",
    "first_principles_rydberg",
    "first_principles_schechter",
    "first_principles_supernovae_zr",
    "first_principles_tully_fisher",
)
ALL_DATASETS = BLACKBOX_DATASETS + FIRST_PRINCIPLES_DATASETS
GLOBAL_SEED = 20260804

THRESHOLDS: dict[str, float | int] = {
    "task_count": 24,
    "candidate_failures_max": 0,
    "overall_median_r2_min": 0.65,
    "overall_worst_r2_min": -1.0,
    "blackbox_mean_r2_min": 0.35,
    "blackbox_median_r2_min": 0.50,
    "firstprinciples_median_r2_min": 0.90,
    "firstprinciples_high_fidelity_min": 7,
    "wins_vs_best_min": 4,
    "within_0_05_of_best_min": 10,
    "mean_gap_vs_best_min": -0.20,
    "median_term_count_max": 8.0,
    "total_runtime_seconds_max": 5400.0,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_seed(name: str) -> int:
    payload = hashlib.sha256(f"{GLOBAL_SEED}|{name}".encode()).digest()
    return int.from_bytes(payload[:4], "big")


def split_indices(n_rows: int, dataset_name: str) -> tuple[np.ndarray, np.ndarray]:
    if n_rows < 40:
        raise ValueError("dataset must contain at least 40 rows")
    rng = np.random.default_rng(stable_seed(dataset_name))
    order = rng.permutation(n_rows)
    n_test = max(20, int(round(0.20 * n_rows)))
    n_test = min(n_test, 3000, n_rows - 20)
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
    if X_train.shape[0] < 20 or X_test.shape[0] < 10:
        raise ValueError("insufficient finite rows")
    scale = max(float(np.max(np.abs(y_train))), float(np.std(y_train)), 1e-300)
    if float(np.std(y_train)) <= np.finfo(float).eps * scale * 16:
        raise ValueError("target is constant relative to its scale")
    return X_train, X_test, y_train, y_test


def _candidate_kwargs(function: Any, seed: int) -> dict[str, Any]:
    parameters = inspect.signature(function).parameters
    candidates: dict[str, Any] = {
        "max_terms": 8,
        "random_state": seed,
        "seed": seed,
    }
    return {name: value for name, value in candidates.items() if name in parameters}


def fit_candidate(X: np.ndarray, y: np.ndarray, seed: int) -> Any:
    from estimator import discover_equation

    return discover_equation(X, y, **_candidate_kwargs(discover_equation, seed))


def candidate_predict(model: Any, X: np.ndarray) -> np.ndarray:
    if hasattr(model, "predict"):
        prediction = model.predict(X)
    elif isinstance(model, dict) and callable(model.get("predict")):
        prediction = model["predict"](X)
    else:
        raise TypeError("candidate result does not expose predict")
    prediction = np.asarray(prediction, dtype=float).reshape(-1)
    if prediction.shape[0] != X.shape[0] or not np.all(np.isfinite(prediction)):
        raise ValueError("candidate prediction is invalid")
    return prediction


def candidate_term_count(model: Any) -> int:
    for name in ("term_count", "n_terms_", "complexity", "complexity_"):
        value = getattr(model, name, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    for name in ("terms", "terms_", "selected_terms"):
        value = getattr(model, name, None)
        if value is not None:
            try:
                return int(len(value))
            except TypeError:
                pass
    if isinstance(model, dict):
        for name in ("term_count", "n_terms", "complexity"):
            if name in model:
                return int(model[name])
        if "terms" in model:
            return int(len(model["terms"]))
    return 999


def baselines(seed: int, n_features: int) -> dict[str, Any]:
    polynomial_degree = 2 if n_features > 12 else 3
    return {
        "mean": DummyRegressor(strategy="mean"),
        "linear": Pipeline(
            [("scale", StandardScaler()), ("model", LinearRegression())]
        ),
        "polynomial_ridge": Pipeline(
            [
                ("poly", PolynomialFeatures(degree=polynomial_degree, include_bias=False)),
                ("scale", StandardScaler()),
                ("model", Ridge(alpha=1.0)),
            ]
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            learning_rate=0.06,
            max_iter=300,
            max_leaf_nodes=31,
            l2_regularization=1e-4,
            random_state=seed,
        ),
        "extra_trees": ExtraTreesRegressor(
            n_estimators=240,
            min_samples_leaf=2,
            max_features=1.0,
            n_jobs=4,
            random_state=seed,
        ),
    }


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    std = max(float(np.std(y_true)), np.finfo(float).tiny)
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "nrmse": float(math.sqrt(mean_squared_error(y_true, y_pred)) / std),
        "nmae": float(mean_absolute_error(y_true, y_pred) / std),
    }


def evaluate_dataset(data_root: Path, dataset_name: str, category: str) -> dict[str, Any]:
    path = data_root / f"{dataset_name}.npz"
    with np.load(path, allow_pickle=False) as payload:
        X = np.asarray(payload["X"], dtype=float)
        y = np.asarray(payload["y"], dtype=float).reshape(-1)
    train_index, test_index = split_indices(X.shape[0], dataset_name)
    X_train, X_test, y_train, y_test = clean_arrays(
        X[train_index], X[test_index], y[train_index], y[test_index]
    )
    seed = stable_seed(dataset_name)
    started = time.perf_counter()
    candidate_error = None
    try:
        candidate = fit_candidate(X_train, y_train, seed)
        candidate_prediction = candidate_predict(candidate, X_test)
        candidate_metrics = metrics(y_test, candidate_prediction)
        term_count = candidate_term_count(candidate)
    except Exception as error:  # evidence must survive a candidate failure
        candidate_error = f"{type(error).__name__}: {error}"
        candidate_metrics = {"r2": -10.0, "nrmse": 1000.0, "nmae": 1000.0}
        term_count = 999
    candidate_runtime = time.perf_counter() - started

    baseline_rows: dict[str, dict[str, float]] = {}
    for name, model in baselines(seed, X_train.shape[1]).items():
        baseline_started = time.perf_counter()
        try:
            model.fit(X_train, y_train)
            prediction = np.asarray(model.predict(X_test), dtype=float).reshape(-1)
            row = metrics(y_test, prediction)
            row["runtime_seconds"] = time.perf_counter() - baseline_started
            baseline_rows[name] = row
        except Exception as error:
            baseline_rows[name] = {
                "r2": -10.0,
                "nrmse": 1000.0,
                "nmae": 1000.0,
                "runtime_seconds": time.perf_counter() - baseline_started,
                "error": f"{type(error).__name__}: {error}",
            }
    best_name, best_row = max(baseline_rows.items(), key=lambda item: item[1]["r2"])
    return {
        "dataset": dataset_name,
        "category": category,
        "rows": int(X.shape[0]),
        "features": int(X.shape[1]),
        "train_rows": int(X_train.shape[0]),
        "test_rows": int(X_test.shape[0]),
        "candidate": {
            **candidate_metrics,
            "runtime_seconds": candidate_runtime,
            "term_count": term_count,
            "error": candidate_error,
        },
        "baselines": baseline_rows,
        "best_baseline": best_name,
        "best_baseline_r2": float(best_row["r2"]),
        "gap_vs_best": float(candidate_metrics["r2"] - best_row["r2"]),
    }


def summarize(rows: list[dict[str, Any]], total_runtime: float) -> dict[str, Any]:
    candidate_r2 = np.array([row["candidate"]["r2"] for row in rows], dtype=float)
    gaps = np.array([row["gap_vs_best"] for row in rows], dtype=float)
    terms = np.array([row["candidate"]["term_count"] for row in rows], dtype=float)
    blackbox = np.array(
        [row["candidate"]["r2"] for row in rows if row["category"] == "blackbox"],
        dtype=float,
    )
    principles = np.array(
        [row["candidate"]["r2"] for row in rows if row["category"] == "firstprinciples"],
        dtype=float,
    )
    return {
        "task_count": len(rows),
        "candidate_failures": sum(row["candidate"]["error"] is not None for row in rows),
        "overall_mean_r2": float(np.mean(candidate_r2)),
        "overall_median_r2": float(np.median(candidate_r2)),
        "overall_worst_r2": float(np.min(candidate_r2)),
        "blackbox_mean_r2": float(np.mean(blackbox)),
        "blackbox_median_r2": float(np.median(blackbox)),
        "firstprinciples_mean_r2": float(np.mean(principles)),
        "firstprinciples_median_r2": float(np.median(principles)),
        "firstprinciples_high_fidelity": int(np.sum(principles >= 0.95)),
        "wins_vs_best": int(np.sum(gaps > 0.0)),
        "within_0_05_of_best": int(np.sum(gaps >= -0.05)),
        "mean_gap_vs_best": float(np.mean(gaps)),
        "median_term_count": float(np.median(terms)),
        "mean_term_count": float(np.mean(terms)),
        "total_runtime_seconds": float(total_runtime),
        "finite_all": bool(np.all(np.isfinite(candidate_r2)) and np.all(np.isfinite(gaps))),
    }


def adjudicate(summary: dict[str, Any]) -> tuple[dict[str, bool], str]:
    checks = {
        "task_count": summary["task_count"] == THRESHOLDS["task_count"],
        "candidate_failures": summary["candidate_failures"] <= THRESHOLDS["candidate_failures_max"],
        "finite_all": bool(summary["finite_all"]),
        "overall_median_r2": summary["overall_median_r2"] >= THRESHOLDS["overall_median_r2_min"],
        "overall_worst_r2": summary["overall_worst_r2"] >= THRESHOLDS["overall_worst_r2_min"],
        "blackbox_mean_r2": summary["blackbox_mean_r2"] >= THRESHOLDS["blackbox_mean_r2_min"],
        "blackbox_median_r2": summary["blackbox_median_r2"] >= THRESHOLDS["blackbox_median_r2_min"],
        "firstprinciples_median_r2": summary["firstprinciples_median_r2"] >= THRESHOLDS["firstprinciples_median_r2_min"],
        "firstprinciples_high_fidelity": summary["firstprinciples_high_fidelity"] >= THRESHOLDS["firstprinciples_high_fidelity_min"],
        "wins_vs_best": summary["wins_vs_best"] >= THRESHOLDS["wins_vs_best_min"],
        "within_0_05_of_best": summary["within_0_05_of_best"] >= THRESHOLDS["within_0_05_of_best_min"],
        "mean_gap_vs_best": summary["mean_gap_vs_best"] >= THRESHOLDS["mean_gap_vs_best_min"],
        "median_term_count": summary["median_term_count"] <= THRESHOLDS["median_term_count_max"],
        "total_runtime_seconds": summary["total_runtime_seconds"] <= THRESHOLDS["total_runtime_seconds_max"],
    }
    return checks, "PASS" if all(checks.values()) else "FAIL"


def run(data_root: Path, output: Path) -> dict[str, Any]:
    started = time.perf_counter()
    rows = [
        evaluate_dataset(data_root, name, "blackbox") for name in BLACKBOX_DATASETS
    ] + [
        evaluate_dataset(data_root, name, "firstprinciples")
        for name in FIRST_PRINCIPLES_DATASETS
    ]
    total_runtime = time.perf_counter() - started
    summary = summarize(rows, total_runtime)
    checks, verdict = adjudicate(summary)
    report = {
        "schema": "data-science-god-level/symbolic-v2-srbench24-report/1",
        "verdict": verdict,
        "thresholds": THRESHOLDS,
        "checks": checks,
        "summary": summary,
        "datasets": rows,
        "candidate_dataset_identifier_access": False,
        "actual_external_evaluation_count": 1,
        "post_hoc_retuning_permitted": False,
    }
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
