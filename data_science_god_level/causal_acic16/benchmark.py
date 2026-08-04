from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from causallib.datasets import load_acic16
from sklearn.linear_model import Ridge
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from estimator import estimate_causal_effect


def _column(frame: Any, name: int) -> np.ndarray:
    if name in frame.columns:
        return np.asarray(frame[name], dtype=np.float64)
    return np.asarray(frame[str(name)], dtype=np.float64)


def _ridge_counterfactuals(
    X: Any, treatment: Any, outcome: Any, *, random_state: int
) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(X, dtype=np.float64)
    a = np.asarray(treatment, dtype=np.int64)
    y = np.asarray(outcome, dtype=np.float64)
    m0 = np.empty(y.size, dtype=np.float64)
    m1 = np.empty(y.size, dtype=np.float64)
    splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)
    for train, test in splitter.split(x, a):
        for arm, target in ((0, m0), (1, m1)):
            rows = a[train] == arm
            model = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
            model.fit(x[train][rows], y[train][rows])
            target[test] = model.predict(x[test])
    return m0, m1


def evaluate_instance(instance: int) -> dict[str, Any]:
    data = load_acic16(instance=instance)
    x = np.asarray(data.X, dtype=np.float64)
    a = np.asarray(data.a, dtype=np.int64)
    y = np.asarray(data.y, dtype=np.float64)
    truth0 = _column(data.po, 0)
    truth1 = _column(data.po, 1)
    true_ite = truth1 - truth0
    true_ate = float(true_ite.mean())
    true_att = float(true_ite[a == 1].mean())

    candidate = estimate_causal_effect(x, a, y, random_state=20260804)
    ridge0, ridge1 = _ridge_counterfactuals(x, a, y, random_state=314159)
    ridge_ite = ridge1 - ridge0
    naive = float(y[a == 1].mean() - y[a == 0].mean())

    row = {
        "instance": instance,
        "n": int(y.size),
        "features": int(x.shape[1]),
        "true": {"ate": true_ate, "att": true_att},
        "candidate": {
            **candidate.summary(),
            "ate_abs_error": abs(candidate.ate - true_ate),
            "att_abs_error": abs(candidate.att - true_att),
            "pehe": float(np.sqrt(np.mean(np.square(candidate.ite - true_ite)))),
            "ate_ci_covers": bool(
                candidate.ate_ci_lower <= true_ate <= candidate.ate_ci_upper
            ),
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
            "pehe": float(np.sqrt(np.mean(np.square(ridge_ite - true_ite)))),
        },
    }
    return row


def _rmse(values: list[float]) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_ate = [row["candidate"]["ate_abs_error"] for row in rows]
    candidate_att = [row["candidate"]["att_abs_error"] for row in rows]
    naive_ate = [row["naive"]["ate_abs_error"] for row in rows]
    naive_att = [row["naive"]["att_abs_error"] for row in rows]
    ridge_ate = [row["ridge_t_learner"]["ate_abs_error"] for row in rows]
    ridge_att = [row["ridge_t_learner"]["att_abs_error"] for row in rows]
    candidate_pehe = [row["candidate"]["pehe"] for row in rows]
    ridge_pehe = [row["ridge_t_learner"]["pehe"] for row in rows]
    coverage = float(np.mean([row["candidate"]["ate_ci_covers"] for row in rows]))

    summary = {
        "instances": [row["instance"] for row in rows],
        "candidate": {
            "ate_rmse": _rmse(candidate_ate),
            "att_rmse": _rmse(candidate_att),
            "mean_pehe": float(np.mean(candidate_pehe)),
            "ate_ci_coverage": coverage,
            "finite_all": bool(
                all(row["candidate"]["diagnostics"]["finite"] for row in rows)
            ),
            "positivity_warnings": int(
                sum(
                    row["candidate"]["diagnostics"]["positivity_warning"]
                    for row in rows
                )
            ),
        },
        "naive": {
            "ate_rmse": _rmse(naive_ate),
            "att_rmse": _rmse(naive_att),
        },
        "ridge_t_learner": {
            "ate_rmse": _rmse(ridge_ate),
            "att_rmse": _rmse(ridge_att),
            "mean_pehe": float(np.mean(ridge_pehe)),
        },
        "wins": {
            "ate_vs_naive": int(sum(c < n for c, n in zip(candidate_ate, naive_ate))),
            "att_vs_naive": int(sum(c < n for c, n in zip(candidate_att, naive_att))),
            "pehe_vs_ridge": int(sum(c < r for c, r in zip(candidate_pehe, ridge_pehe))),
        },
    }
    required_wins = max(1, len(rows) // 2)
    gate_checks = {
        "finite": summary["candidate"]["finite_all"],
        "ate_beats_naive_rmse": (
            summary["candidate"]["ate_rmse"] < summary["naive"]["ate_rmse"]
        ),
        "att_beats_naive_rmse": (
            summary["candidate"]["att_rmse"] < summary["naive"]["att_rmse"]
        ),
        "pehe_beats_ridge_mean": (
            summary["candidate"]["mean_pehe"]
            < summary["ridge_t_learner"]["mean_pehe"]
        ),
        "coverage_at_least_half": coverage >= 0.5,
        "ate_wins_at_least_half": summary["wins"]["ate_vs_naive"] >= required_wins,
        "att_wins_at_least_half": summary["wins"]["att_vs_naive"] >= required_wins,
    }
    summary["gate_checks"] = gate_checks
    summary["verdict"] = "PASS" if all(gate_checks.values()) else "FAIL"
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", nargs="+", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    if not args.instances or any(instance < 1 or instance > 10 for instance in args.instances):
        raise SystemExit("instances must be between 1 and 10")

    rows = [evaluate_instance(instance) for instance in args.instances]
    report = {
        "schema": "data-science-god-level/acic16-benchmark/2",
        "dataset": "ACIC 2016 sample packaged by causallib 0.10.0",
        "candidate_ground_truth_access": False,
        "instances": rows,
        "summary": summarize(rows),
    }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")

    canonical_output = Path(__file__).resolve().parents[2] / "public-logs" / "public-report.json"
    if canonical_output.resolve() != args.output.resolve():
        canonical_output.parent.mkdir(parents=True, exist_ok=True)
        canonical_output.write_text(payload, encoding="utf-8")

    digest = hashlib.sha256(payload.encode()).hexdigest()
    print(payload)
    print(f"report_sha256={digest}")
    if args.enforce and report["summary"]["verdict"] != "PASS":
        raise SystemExit("ACIC16 public gate failed")


if __name__ == "__main__":
    main()
