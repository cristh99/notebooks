from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from estimator import estimate_causal_effect


TRUTH_COLUMNS = {"t", "treatment", "y", "y0", "y1", "ite"}


def _load(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    frame = pd.read_csv(path)
    lower = {str(column).lower(): column for column in frame.columns}
    treatment_column = lower.get("t", lower.get("treatment"))
    required = {"y", "y0", "y1"}
    if treatment_column is None or not required.issubset(lower):
        raise ValueError(f"missing causal columns in {path.name}: {list(frame.columns)}")
    excluded = TRUTH_COLUMNS | {
        name for name in lower if name.startswith("unnamed") or name in {"index", "id"}
    }
    feature_columns = [column for column in frame.columns if str(column).lower() not in excluded]
    if not feature_columns:
        raise ValueError(f"no covariates in {path.name}")
    x = frame[feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    a = pd.to_numeric(frame[treatment_column], errors="raise").to_numpy(int)
    y = pd.to_numeric(frame[lower["y"]], errors="raise").to_numpy(float)
    y0 = pd.to_numeric(frame[lower["y0"]], errors="raise").to_numpy(float)
    y1 = pd.to_numeric(frame[lower["y1"]], errors="raise").to_numpy(float)
    return x, a, y, y0, y1


def _ridge_counterfactuals(
    x: np.ndarray, a: np.ndarray, y: np.ndarray, *, random_state: int
) -> tuple[np.ndarray, np.ndarray]:
    m0 = np.empty(y.size, dtype=float)
    m1 = np.empty(y.size, dtype=float)
    splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)
    for train, test in splitter.split(x, a):
        for arm, target in ((0, m0), (1, m1)):
            rows = a[train] == arm
            model = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
            model.fit(x[train][rows], y[train][rows])
            target[test] = model.predict(x[test])
    return m0, m1


def evaluate(path: Path) -> dict[str, Any]:
    x, a, y, y0, y1 = _load(path)
    truth_ite = y1 - y0
    true_ate = float(truth_ite.mean())
    true_att = float(truth_ite[a == 1].mean())
    candidate = estimate_causal_effect(x, a, y, random_state=20260804)
    ridge0, ridge1 = _ridge_counterfactuals(x, a, y, random_state=314159)
    ridge_ite = ridge1 - ridge0
    naive = float(y[a == 1].mean() - y[a == 0].mean())
    return {
        "file": path.name,
        "family": path.name.rsplit("_sample", 1)[0],
        "n": int(y.size),
        "features": int(x.shape[1]),
        "true": {"ate": true_ate, "att": true_att},
        "candidate": {
            **candidate.summary(),
            "ate_abs_error": abs(candidate.ate - true_ate),
            "att_abs_error": abs(candidate.att - true_att),
            "pehe": float(np.sqrt(np.mean(np.square(candidate.ite - truth_ite)))),
            "ate_ci_covers": bool(candidate.ate_ci_lower <= true_ate <= candidate.ate_ci_upper),
        },
        "naive": {
            "ate": naive,
            "att": naive,
            "ate_abs_error": abs(naive - true_ate),
            "att_abs_error": abs(naive - true_att),
        },
        "ridge_t_learner": {
            "ate": float(ridge_ite.mean()),
            "att": float(ridge_ite[a == 1].mean()),
            "ate_abs_error": abs(float(ridge_ite.mean()) - true_ate),
            "att_abs_error": abs(float(ridge_ite[a == 1].mean()) - true_att),
            "pehe": float(np.sqrt(np.mean(np.square(ridge_ite - truth_ite)))),
        },
    }


def _rmse(values: list[float]) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, dict[str, float]] = {}
    for method in ("candidate", "naive", "ridge_t_learner"):
        metrics[method] = {
            "ate_rmse": _rmse([row[method]["ate_abs_error"] for row in rows]),
            "att_rmse": _rmse([row[method]["att_abs_error"] for row in rows]),
        }
        if method != "naive":
            metrics[method]["mean_pehe"] = float(np.mean([row[method]["pehe"] for row in rows]))
    metrics["candidate"]["ate_ci_coverage"] = float(
        np.mean([row["candidate"]["ate_ci_covers"] for row in rows])
    )
    metrics["candidate"]["finite_all"] = bool(
        all(row["candidate"]["diagnostics"]["finite"] for row in rows)
    )
    wins = {
        "ate_vs_naive": sum(row["candidate"]["ate_abs_error"] < row["naive"]["ate_abs_error"] for row in rows),
        "att_vs_naive": sum(row["candidate"]["att_abs_error"] < row["naive"]["att_abs_error"] for row in rows),
        "ate_vs_ridge": sum(row["candidate"]["ate_abs_error"] < row["ridge_t_learner"]["ate_abs_error"] for row in rows),
        "att_vs_ridge": sum(row["candidate"]["att_abs_error"] < row["ridge_t_learner"]["att_abs_error"] for row in rows),
        "pehe_vs_ridge": sum(row["candidate"]["pehe"] < row["ridge_t_learner"]["pehe"] for row in rows),
    }
    half = (len(rows) + 1) // 2
    checks = {
        "finite_all": metrics["candidate"]["finite_all"],
        "ate_rmse_below_naive": metrics["candidate"]["ate_rmse"] < metrics["naive"]["ate_rmse"],
        "att_rmse_below_naive": metrics["candidate"]["att_rmse"] < metrics["naive"]["att_rmse"],
        "ate_rmse_below_ridge": metrics["candidate"]["ate_rmse"] < metrics["ridge_t_learner"]["ate_rmse"],
        "att_rmse_below_ridge": metrics["candidate"]["att_rmse"] < metrics["ridge_t_learner"]["att_rmse"],
        "pehe_below_ridge": metrics["candidate"]["mean_pehe"] < metrics["ridge_t_learner"]["mean_pehe"],
        "coverage_at_least_half": metrics["candidate"]["ate_ci_coverage"] >= 0.5,
        "ate_wins_vs_naive_half": wins["ate_vs_naive"] >= half,
        "att_wins_vs_naive_half": wins["att_vs_naive"] >= half,
        "pehe_wins_vs_ridge_half": wins["pehe_vs_ridge"] >= half,
    }
    return {
        **metrics,
        "wins": wins,
        "checks": checks,
        "verdict": "PASS" if all(checks.values()) else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [evaluate(path) for path in args.files]
    report = {
        "schema": "data-science-god-level/realcause-benchmark/1",
        "candidate_ground_truth_access": False,
        "files": rows,
        "summary": summarize(rows),
    }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload)
    print(f"report_sha256={hashlib.sha256(payload.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
