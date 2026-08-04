from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickletools
import re
from time import perf_counter

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from estimator import discover_equation


DATASET_IDS = (
    "I.12.1", "I.12.4", "I.12.5", "I.14.3", "I.14.4",
    "I.18.12", "I.18.16", "I.25.13", "I.26.2", "I.27.6",
    "I.30.5", "I.43.16", "I.47.23", "II.2.42", "II.3.24",
    "II.4.23", "II.8.31", "II.10.9", "II.13.17", "II.15.4",
    "II.15.5", "II.27.16", "II.27.18", "II.34.11", "II.34.29b",
    "II.38.3", "II.38.14", "III.7.38", "III.12.43", "III.15.27",
)

ONE_DUMMY = {
    "I.12.1", "I.12.4", "I.12.5", "I.18.12", "I.25.13", "I.47.23",
}
TWO_DUMMIES = {
    "I.14.3", "I.18.16", "I.43.16", "II.3.24", "II.8.31",
    "II.10.9", "II.13.17", "II.15.5", "II.27.18", "III.7.38",
    "III.12.43",
}
THREE_DUMMIES = set(DATASET_IDS) - ONE_DUMMY - TWO_DUMMIES

THRESHOLDS: dict[str, float | int] = {
    "task_count": 30,
    "candidate_mean_test_r2_min": 0.85,
    "candidate_median_test_r2_min": 0.95,
    "candidate_worst_test_r2_min": -0.50,
    "high_fidelity_count_min": 12,
    "usable_count_min": 20,
    "candidate_mean_variable_f1_min": 0.75,
    "exact_variable_sets_min": 15,
    "mean_gap_vs_best_min": -0.08,
    "within_0_02_of_best_count_min": 12,
    "candidate_mean_term_count_max": 4.0,
}


def _slug(dataset_id: str) -> str:
    return dataset_id.lower()


def _dummy_count(dataset_id: str) -> int:
    if dataset_id in ONE_DUMMY:
        return 1
    if dataset_id in TWO_DUMMIES:
        return 2
    if dataset_id in THREE_DUMMIES:
        return 3
    raise KeyError(dataset_id)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_table(path: Path) -> tuple[np.ndarray, np.ndarray]:
    table = np.loadtxt(path, dtype=float)
    if table.ndim != 2 or table.shape[1] < 2:
        raise ValueError(f"invalid SRSD table: {path}")
    X = table[:, :-1]
    y = table[:, -1]
    if not np.all(np.isfinite(X)) or not np.all(np.isfinite(y)):
        raise ValueError(f"non-finite SRSD values: {path}")
    return X, y


def _safe_symbol_indices(path: Path) -> tuple[int, ...]:
    """Extract xN strings from a pickle bytecode stream without unpickling."""
    indices: set[int] = set()
    for opcode, argument, _ in pickletools.genops(path.read_bytes()):
        if opcode.name not in {
            "UNICODE", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8"
        }:
            continue
        match = re.fullmatch(r"x(\d+)", str(argument))
        if match:
            indices.add(int(match.group(1)))
    if not indices:
        raise ValueError(f"no symbolic variables found safely in {path}")
    return tuple(sorted(indices))


def _variable_f1(predicted: set[int], truth: set[int]) -> float:
    if not predicted and not truth:
        return 1.0
    if not predicted or not truth:
        return 0.0
    overlap = len(predicted & truth)
    precision = overlap / len(predicted)
    recall = overlap / len(truth)
    return float(2 * precision * recall / (precision + recall))


def _nrmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(
        np.sqrt(np.mean((y_true - y_pred) ** 2))
        / (float(np.std(y_true)) + 1e-12)
    )


def _baseline_models(seed: int) -> dict[str, object]:
    return {
        "linear": make_pipeline(
            StandardScaler(),
            LinearRegression(),
        ),
        "polynomial_degree_3": make_pipeline(
            StandardScaler(),
            PolynomialFeatures(degree=3, include_bias=False),
            Ridge(alpha=1e-4),
        ),
        "random_forest": RandomForestRegressor(
            n_estimators=160,
            min_samples_leaf=3,
            max_features=0.8,
            random_state=seed,
            n_jobs=1,
        ),
    }


def _evaluate_task(
    data_root: Path,
    dataset_id: str,
    index: int,
) -> dict[str, object]:
    started = perf_counter()
    slug = _slug(dataset_id)
    train_path = data_root / "train" / f"feynman-{slug}.txt"
    test_path = data_root / "test" / f"feynman-{slug}.txt"
    truth_path = data_root / "true_eq" / f"feynman-{slug}.pkl"

    X_all, y_all = _load_table(train_path)
    X_test, y_test = _load_table(test_path)
    if X_all.shape[1] != X_test.shape[1]:
        raise ValueError(f"feature mismatch for {dataset_id}")
    if X_all.shape[0] < 1200 or X_test.shape[0] < 1000:
        raise ValueError(f"insufficient rows for {dataset_id}")

    sample_rng = np.random.default_rng(7103 + index * 97)
    train_rows = np.sort(sample_rng.choice(X_all.shape[0], 1200, replace=False))
    X_train = X_all[train_rows]
    y_train = y_all[train_rows]

    truth_variables = set(_safe_symbol_indices(truth_path))
    if max(truth_variables) >= X_train.shape[1]:
        raise ValueError(f"truth index outside table for {dataset_id}")
    expected_dummy_count = _dummy_count(dataset_id)
    observed_dummy_count = X_train.shape[1] - len(truth_variables)
    if observed_dummy_count != expected_dummy_count:
        raise ValueError(
            f"dummy count mismatch for {dataset_id}: "
            f"expected {expected_dummy_count}, observed {observed_dummy_count}"
        )

    equation = discover_equation(
        X_train,
        y_train,
        max_terms=4,
        random_state=1709 + index * 31,
    )
    candidate_prediction = equation.predict(X_test)
    candidate_r2 = float(r2_score(y_test, candidate_prediction))
    candidate_nrmse = _nrmse(y_test, candidate_prediction)
    predicted_variables = {
        variable
        for group in equation.term_variables
        for variable in group
    }
    variable_f1 = _variable_f1(predicted_variables, truth_variables)
    exact_variable_set = predicted_variables == truth_variables

    baselines: dict[str, dict[str, float]] = {}
    for name, model in _baseline_models(2203 + index * 43).items():
        try:
            model.fit(X_train, y_train)
            prediction = np.asarray(model.predict(X_test), dtype=float)
            baselines[name] = {
                "test_r2": float(r2_score(y_test, prediction)),
                "test_nrmse": _nrmse(y_test, prediction),
            }
        except Exception as error:  # evidence records bounded baseline failure
            baselines[name] = {
                "test_r2": -1e9,
                "test_nrmse": 1e9,
                "error": f"{type(error).__name__}: {error}",
            }

    best_baseline = max(
        baselines,
        key=lambda name: baselines[name]["test_r2"],
    )
    best_baseline_r2 = float(baselines[best_baseline]["test_r2"])
    gap = candidate_r2 - best_baseline_r2
    within_0_02 = gap >= -0.02

    return {
        "dataset_id": dataset_id,
        "role": f"e{index + 1:02d}",
        "train_rows_total": int(X_all.shape[0]),
        "train_rows_used": int(X_train.shape[0]),
        "test_rows": int(X_test.shape[0]),
        "feature_count": int(X_train.shape[1]),
        "expected_dummy_count": expected_dummy_count,
        "truth_variable_indices": sorted(truth_variables),
        "predicted_variable_indices": sorted(predicted_variables),
        "candidate_equation": equation.to_dict(),
        "candidate": {
            "test_r2": candidate_r2,
            "test_nrmse": candidate_nrmse,
            "variable_f1": variable_f1,
            "exact_variable_set": exact_variable_set,
            "term_count": len(equation.term_names),
            "selected_complexity": equation.selected_complexity,
        },
        "baselines": baselines,
        "best_baseline": best_baseline,
        "gap_vs_best": gap,
        "within_0_02_of_best": within_0_02,
        "data_hashes": {
            "train_sha256": _sha256(train_path),
            "test_sha256": _sha256(test_path),
            "truth_pickle_sha256": _sha256(truth_path),
        },
        "truth_pickle_executed": False,
        "elapsed_seconds": perf_counter() - started,
    }


def _summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    candidate_r2 = np.asarray(
        [row["candidate"]["test_r2"] for row in rows],
        dtype=float,
    )
    variable_f1 = np.asarray(
        [row["candidate"]["variable_f1"] for row in rows],
        dtype=float,
    )
    gaps = np.asarray([row["gap_vs_best"] for row in rows], dtype=float)
    term_counts = np.asarray(
        [row["candidate"]["term_count"] for row in rows],
        dtype=float,
    )
    return {
        "task_count": len(rows),
        "finite_all": bool(
            np.all(np.isfinite(candidate_r2))
            and np.all(np.isfinite(variable_f1))
            and np.all(np.isfinite(gaps))
        ),
        "candidate_mean_test_r2": float(np.mean(candidate_r2)),
        "candidate_median_test_r2": float(np.median(candidate_r2)),
        "candidate_worst_test_r2": float(np.min(candidate_r2)),
        "high_fidelity_count": int(np.sum(candidate_r2 >= 0.99)),
        "usable_count": int(np.sum(candidate_r2 >= 0.90)),
        "candidate_mean_variable_f1": float(np.mean(variable_f1)),
        "exact_variable_sets": int(
            sum(row["candidate"]["exact_variable_set"] for row in rows)
        ),
        "mean_gap_vs_best": float(np.mean(gaps)),
        "within_0_02_of_best_count": int(
            sum(row["within_0_02_of_best"] for row in rows)
        ),
        "candidate_mean_term_count": float(np.mean(term_counts)),
        "total_elapsed_seconds": float(
            sum(row["elapsed_seconds"] for row in rows)
        ),
    }


def _adjudicate(summary: dict[str, object]) -> tuple[str, dict[str, bool]]:
    checks = {
        "task_count": summary["task_count"] == THRESHOLDS["task_count"],
        "finite_all": bool(summary["finite_all"]),
        "candidate_mean_test_r2": summary["candidate_mean_test_r2"] >= THRESHOLDS["candidate_mean_test_r2_min"],
        "candidate_median_test_r2": summary["candidate_median_test_r2"] >= THRESHOLDS["candidate_median_test_r2_min"],
        "candidate_worst_test_r2": summary["candidate_worst_test_r2"] >= THRESHOLDS["candidate_worst_test_r2_min"],
        "high_fidelity_count": summary["high_fidelity_count"] >= THRESHOLDS["high_fidelity_count_min"],
        "usable_count": summary["usable_count"] >= THRESHOLDS["usable_count_min"],
        "candidate_mean_variable_f1": summary["candidate_mean_variable_f1"] >= THRESHOLDS["candidate_mean_variable_f1_min"],
        "exact_variable_sets": summary["exact_variable_sets"] >= THRESHOLDS["exact_variable_sets_min"],
        "mean_gap_vs_best": summary["mean_gap_vs_best"] >= THRESHOLDS["mean_gap_vs_best_min"],
        "within_0_02_of_best_count": summary["within_0_02_of_best_count"] >= THRESHOLDS["within_0_02_of_best_count_min"],
        "candidate_mean_term_count": summary["candidate_mean_term_count"] <= THRESHOLDS["candidate_mean_term_count_max"],
    }
    return ("PASS" if all(checks.values()) else "FAIL"), checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--logs-dir", required=True)
    parser.add_argument("--code-root", required=True)
    arguments = parser.parse_args()

    data_root = Path(arguments.data_root).resolve()
    logs = Path(arguments.logs_dir).resolve()
    code_root = Path(arguments.code_root).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report_path = logs / "srsd-external-report.json"
    receipt_path = logs / "srsd-external-freeze-receipt.json"
    if report_path.exists() or receipt_path.exists():
        raise SystemExit("external output already exists; rerun prohibited")

    rows = [
        _evaluate_task(data_root, dataset_id, index)
        for index, dataset_id in enumerate(DATASET_IDS)
    ]
    summary = _summarize(rows)
    report = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-external-report/1",
        "source": {
            "repository": "yoshitomo-matsubara/srsd-feynman_easy_dummy",
            "commit": "67a1cac8420adf421fd0a18d91fbee5f1c0bca2d",
            "license": "CC-BY-4.0",
            "paper": "Rethinking Symbolic Regression Datasets and Benchmarks for Scientific Discovery",
        },
        "selection_rule": "all 30 equations in SRSD-Feynman Easy with dummy variables; no compatibility filtering",
        "candidate_truth_access": False,
        "truth_pickle_executed": False,
        "training_rows_per_task": 1200,
        "tasks": rows,
        "summary": summary,
    }
    report_payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(report_payload, encoding="utf-8")

    verdict, checks = _adjudicate(summary)
    receipt = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-external-freeze/1",
        "verdict": verdict,
        "actual_external_evaluation_count": 1,
        "candidate_frozen_before_srsd_data_access": True,
        "candidate_truth_access": False,
        "truth_pickle_executed": False,
        "post_hoc_retuning_permitted": False,
        "dataset_selection_post_hoc": False,
        "dataset_selection_rule": "all 30 SRSD-Feynman Easy Dummy tasks",
        "thresholds": THRESHOLDS,
        "checks": checks,
        "summary": summary,
        "hashes": {
            "estimator_sha256": _sha256(code_root / "estimator.py"),
            "external_runner_sha256": _sha256(code_root / "srsd_external_runner.py"),
            "external_plan_source_sha256": _sha256(code_root / "srsd_external_plan.py"),
            "external_plan_receipt_sha256": _sha256(code_root / "srsd-external-plan-receipt.json"),
            "external_test_sha256": _sha256(code_root / "test_srsd_external_runner.py"),
            "external_manifest_sha256": _sha256(code_root / "SRSD_EXTERNAL_MANIFEST.json"),
            "report_sha256": _sha256(report_path),
        },
    }
    receipt_payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    receipt_path.write_text(receipt_payload, encoding="utf-8")
    (logs / "srsd-external-freeze-receipt.sha256").write_text(
        hashlib.sha256(receipt_payload.encode("utf-8")).hexdigest()
        + "  srsd-external-freeze-receipt.json\n",
        encoding="utf-8",
    )
    print(receipt_payload)
    if verdict != "PASS":
        raise SystemExit(
            "SRSD external symbolic gate failed; evidence preserved; retuning prohibited"
        )


if __name__ == "__main__":
    main()
