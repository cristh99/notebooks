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
    "I.10.7", "I.12.2", "I.13.12", "I.16.6", "I.32.5",
    "I.43.31", "II.11.3", "II.34.2", "II.34.29a", "III.14.14",
    "III.15.14", "B8", "I.11.19", "I.12.11", "I.13.4",
    "I.15.10", "I.18.4", "I.24.6", "I.34.8", "I.38.12",
    "I.39.11", "I.43.43", "I.48.2", "II.6.11", "II.21.32",
    "II.34.2a", "III.4.32", "III.13.18", "III.15.12", "III.17.37",
    "I.8.14", "I.29.4", "I.34.10", "I.34.27", "I.39.10",
    "II.8.7", "II.37.1", "III.8.54", "III.19.51", "B18",
)

ONE_DUMMY = {
    "I.10.7", "I.12.2", "I.13.12", "I.16.6", "I.32.5", "I.43.31",
    "II.11.3", "II.34.2", "II.34.29a", "III.14.14", "III.15.14", "B8",
}
TWO_DUMMIES = {
    "I.11.19", "I.12.11", "I.13.4", "I.15.10", "I.18.4", "I.24.6",
    "I.34.8", "I.38.12", "I.39.11", "I.43.43", "I.48.2", "II.6.11",
    "II.21.32", "II.34.2a", "III.4.32", "III.13.18", "III.15.12",
    "III.17.37",
}
THREE_DUMMIES = set(DATASET_IDS) - ONE_DUMMY - TWO_DUMMIES

FAILURE_R2 = -10.0
FAILURE_NRMSE = 1_000.0

THRESHOLDS: dict[str, float | int] = {
    "task_count": 40,
    "candidate_failures_max": 0,
    "candidate_mean_test_r2_min": 0.80,
    "candidate_median_test_r2_min": 0.90,
    "candidate_worst_test_r2_min": -1.00,
    "high_fidelity_count_min": 12,
    "usable_count_min": 24,
    "candidate_mean_variable_f1_min": 0.70,
    "exact_variable_sets_min": 18,
    "mean_gap_vs_best_min": -0.12,
    "within_0_02_of_best_count_min": 16,
    "candidate_mean_term_count_max": 4.0,
}


def _slug(dataset_id: str) -> str:
    if dataset_id == "B8":
        return "bonus.8"
    if dataset_id == "B18":
        return "bonus.18"
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
        "linear": make_pipeline(StandardScaler(), LinearRegression()),
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


def _candidate_failure(error: Exception) -> dict[str, object]:
    return {
        "test_r2": FAILURE_R2,
        "test_nrmse": FAILURE_NRMSE,
        "variable_f1": 0.0,
        "exact_variable_set": False,
        "term_count": 0,
        "selected_complexity": 0,
        "error": f"{type(error).__name__}: {error}",
    }


def _evaluate_task(data_root: Path, dataset_id: str, index: int) -> dict[str, object]:
    started = perf_counter()
    slug = _slug(dataset_id)
    train_path = data_root / "train" / f"feynman-{slug}.txt"
    test_path = data_root / "test" / f"feynman-{slug}.txt"
    truth_path = data_root / "true_eq" / f"feynman-{slug}.pkl"

    X_train, y_train = _load_table(train_path)
    X_test, y_test = _load_table(test_path)
    if X_train.shape[1] != X_test.shape[1]:
        raise ValueError(f"feature mismatch for {dataset_id}")
    if X_train.shape[0] != 8000 or X_test.shape[0] != 1000:
        raise ValueError(f"unexpected row count for {dataset_id}")

    truth_variables = set(_safe_symbol_indices(truth_path))
    if max(truth_variables) >= X_train.shape[1]:
        raise ValueError(f"truth index outside table for {dataset_id}")
    expected_dummy_count = _dummy_count(dataset_id)
    observed_dummy_count = X_train.shape[1] - len(truth_variables)
    if observed_dummy_count != expected_dummy_count:
        raise ValueError(
            f"dummy count mismatch for {dataset_id}: expected {expected_dummy_count}, "
            f"observed {observed_dummy_count}"
        )

    equation_payload: dict[str, object] | None = None
    predicted_variables: set[int] = set()
    candidate_failed = False
    try:
        equation = discover_equation(
            X_train,
            y_train,
            max_terms=4,
            random_state=3109 + index * 37,
        )
        prediction = equation.predict(X_test)
        predicted_variables = {
            variable for group in equation.term_variables for variable in group
        }
        candidate = {
            "test_r2": float(r2_score(y_test, prediction)),
            "test_nrmse": _nrmse(y_test, prediction),
            "variable_f1": _variable_f1(predicted_variables, truth_variables),
            "exact_variable_set": predicted_variables == truth_variables,
            "term_count": len(equation.term_names),
            "selected_complexity": equation.selected_complexity,
        }
        equation_payload = equation.to_dict()
    except Exception as error:
        candidate_failed = True
        candidate = _candidate_failure(error)

    baselines: dict[str, dict[str, object]] = {}
    for name, model in _baseline_models(4201 + index * 43).items():
        try:
            model.fit(X_train, y_train)
            prediction = np.asarray(model.predict(X_test), dtype=float)
            baselines[name] = {
                "test_r2": float(r2_score(y_test, prediction)),
                "test_nrmse": _nrmse(y_test, prediction),
            }
        except Exception as error:
            baselines[name] = {
                "test_r2": FAILURE_R2,
                "test_nrmse": FAILURE_NRMSE,
                "error": f"{type(error).__name__}: {error}",
            }

    best_baseline = max(baselines, key=lambda name: float(baselines[name]["test_r2"]))
    best_baseline_r2 = float(baselines[best_baseline]["test_r2"])
    gap = float(candidate["test_r2"]) - best_baseline_r2

    return {
        "dataset_id": dataset_id,
        "role": f"m{index + 1:02d}",
        "train_rows": int(X_train.shape[0]),
        "test_rows": int(X_test.shape[0]),
        "feature_count": int(X_train.shape[1]),
        "expected_dummy_count": expected_dummy_count,
        "truth_variable_indices": sorted(truth_variables),
        "predicted_variable_indices": sorted(predicted_variables),
        "candidate_failed": candidate_failed,
        "candidate_equation": equation_payload,
        "candidate": candidate,
        "baselines": baselines,
        "best_baseline": best_baseline,
        "gap_vs_best": gap,
        "within_0_02_of_best": gap >= -0.02,
        "data_hashes": {
            "train_sha256": _sha256(train_path),
            "test_sha256": _sha256(test_path),
            "truth_pickle_sha256": _sha256(truth_path),
        },
        "truth_pickle_executed": False,
        "elapsed_seconds": perf_counter() - started,
    }


def _summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    r2 = np.asarray([row["candidate"]["test_r2"] for row in rows], dtype=float)
    f1 = np.asarray([row["candidate"]["variable_f1"] for row in rows], dtype=float)
    gaps = np.asarray([row["gap_vs_best"] for row in rows], dtype=float)
    terms = np.asarray([row["candidate"]["term_count"] for row in rows], dtype=float)
    return {
        "task_count": len(rows),
        "finite_all": bool(np.all(np.isfinite(r2)) and np.all(np.isfinite(f1)) and np.all(np.isfinite(gaps))),
        "candidate_failures": int(sum(row["candidate_failed"] for row in rows)),
        "candidate_mean_test_r2": float(np.mean(r2)),
        "candidate_median_test_r2": float(np.median(r2)),
        "candidate_worst_test_r2": float(np.min(r2)),
        "high_fidelity_count": int(np.sum(r2 >= 0.99)),
        "usable_count": int(np.sum(r2 >= 0.90)),
        "candidate_mean_variable_f1": float(np.mean(f1)),
        "exact_variable_sets": int(sum(row["candidate"]["exact_variable_set"] for row in rows)),
        "mean_gap_vs_best": float(np.mean(gaps)),
        "within_0_02_of_best_count": int(sum(row["within_0_02_of_best"] for row in rows)),
        "candidate_mean_term_count": float(np.mean(terms)),
        "total_elapsed_seconds": float(sum(row["elapsed_seconds"] for row in rows)),
    }


def _adjudicate(summary: dict[str, object]) -> tuple[str, dict[str, bool]]:
    checks = {
        "task_count": summary["task_count"] == THRESHOLDS["task_count"],
        "finite_all": bool(summary["finite_all"]),
        "candidate_failures": summary["candidate_failures"] <= THRESHOLDS["candidate_failures_max"],
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
    args = parser.parse_args()
    data_root = Path(args.data_root).resolve()
    logs = Path(args.logs_dir).resolve()
    code_root = Path(args.code_root).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report_path = logs / "srsd-medium-report.json"
    receipt_path = logs / "srsd-medium-freeze-receipt.json"
    if report_path.exists() or receipt_path.exists():
        raise SystemExit("medium external output already exists; rerun prohibited")

    rows = [_evaluate_task(data_root, dataset_id, index) for index, dataset_id in enumerate(DATASET_IDS)]
    summary = _summarize(rows)
    report = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-medium-report/1",
        "source": {
            "repository": "yoshitomo-matsubara/srsd-feynman_medium_dummy",
            "commit": "8d562c9ea19be1e9de336e3d2a30000723c5c8f6",
            "license": "CC-BY-4.0",
            "dataset_doi": "10.57967/hf/0759",
        },
        "selection_rule": "all 40 SRSD-Feynman Medium Dummy equations; no compatibility filtering",
        "candidate_truth_access": False,
        "truth_pickle_executed": False,
        "training_rows_per_task": 8000,
        "tasks": rows,
        "summary": summary,
    }
    report_payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(report_payload, encoding="utf-8")

    verdict, checks = _adjudicate(summary)
    receipt = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-medium-freeze/1",
        "verdict": verdict,
        "actual_external_evaluation_count": 1,
        "candidate_frozen_before_medium_data_access": True,
        "candidate_truth_access": False,
        "truth_pickle_executed": False,
        "post_hoc_retuning_permitted": False,
        "dataset_selection_post_hoc": False,
        "dataset_selection_rule": "all 40 SRSD-Feynman Medium Dummy equations",
        "failure_scoring": {"test_r2": FAILURE_R2, "test_nrmse": FAILURE_NRMSE},
        "thresholds": THRESHOLDS,
        "checks": checks,
        "summary": summary,
        "hashes": {
            "estimator_sha256": _sha256(code_root / "estimator.py"),
            "runner_sha256": _sha256(code_root / "srsd_medium_runner.py"),
            "plan_source_sha256": _sha256(code_root / "srsd_medium_plan.py"),
            "plan_receipt_sha256": _sha256(code_root / "srsd-medium-plan-receipt.json"),
            "test_sha256": _sha256(code_root / "test_srsd_medium_runner.py"),
            "manifest_sha256": _sha256(code_root / "SRSD_MEDIUM_MANIFEST.json"),
            "report_sha256": _sha256(report_path),
        },
    }
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    receipt_path.write_text(payload, encoding="utf-8")
    (logs / "srsd-medium-freeze-receipt.sha256").write_text(
        hashlib.sha256(payload.encode("utf-8")).hexdigest() + "  srsd-medium-freeze-receipt.json\n",
        encoding="utf-8",
    )
    print(payload)
    if verdict != "PASS":
        raise SystemExit("SRSD Medium external gate failed; evidence preserved; retuning prohibited")


if __name__ == "__main__":
    main()
