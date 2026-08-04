from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors

from estimator import _as_finite_matrix, score_anomalies


def _load_dataset(path: str) -> tuple[np.ndarray, np.ndarray]:
    payload = np.load(path, allow_pickle=True)
    X = np.asarray(payload["X"], dtype=float)
    y = np.asarray(payload["y"]).reshape(-1)
    if X.shape[0] != y.shape[0]:
        raise ValueError("X and y row counts differ")
    unique = np.unique(y)
    if unique.size != 2:
        raise ValueError(f"binary anomaly labels required, got {unique.tolist()}")
    y = (y == unique.max()).astype(int)
    if y.min() != 0 or y.max() != 1:
        raise ValueError("labels could not be normalized to 0/1")
    return X, y


def _distance_representation(Z: np.ndarray, seed: int) -> np.ndarray:
    n, d = Z.shape
    if d <= 24:
        return Z
    return PCA(
        n_components=min(32, d, n - 1),
        whiten=True,
        random_state=seed,
    ).fit_transform(Z)


def _fixed_baselines(X: np.ndarray, seed: int) -> dict[str, np.ndarray]:
    Z = _as_finite_matrix(X)
    distance = _distance_representation(Z, seed)
    n = len(Z)
    isolation = IsolationForest(
        n_estimators=256,
        max_samples=min(1024, n),
        contamination="auto",
        random_state=seed,
        n_jobs=-1,
    ).fit(Z)
    k = min(20, n - 1)
    neighbors = NearestNeighbors(n_neighbors=k + 1, n_jobs=-1).fit(distance)
    distances = neighbors.kneighbors(return_distance=True)[0][:, 1:]
    lof = LocalOutlierFactor(
        n_neighbors=k,
        contamination="auto",
        novelty=False,
        n_jobs=-1,
    )
    lof.fit_predict(distance)
    return {
        "isolation_forest": -isolation.score_samples(Z),
        "knn_20": 0.65 * distances[:, -1] + 0.35 * distances.mean(axis=1),
        "lof_20": -np.asarray(lof.negative_outlier_factor_, dtype=float),
    }


def _metrics(y: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    values = np.asarray(scores, dtype=float).reshape(-1)
    if values.shape[0] != y.shape[0] or not np.isfinite(values).all():
        raise ValueError("invalid anomaly scores")
    prevalence = float(np.mean(y))
    auc = float(roc_auc_score(y, values))
    ap = float(average_precision_score(y, values))
    roc_skill = float(2.0 * auc - 1.0)
    ap_skill = float((ap - prevalence) / max(1.0 - prevalence, 1e-12))
    combined = float(0.5 * roc_skill + 0.5 * ap_skill)
    return {
        "roc_auc": auc,
        "average_precision": ap,
        "prevalence": prevalence,
        "roc_skill": roc_skill,
        "ap_skill": ap_skill,
        "combined_skill": combined,
    }


def run(manifest: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for item in manifest["datasets"]:
        role = str(item["role"])
        seed = int(item["seed"])
        X, y = _load_dataset(str(item["path"]))
        item_started = time.perf_counter()
        candidate = score_anomalies(X, random_state=seed)
        candidate_metrics = _metrics(y, candidate.scores)
        baselines = {
            name: _metrics(y, scores)
            for name, scores in _fixed_baselines(X, seed).items()
        }
        best_name = max(
            baselines,
            key=lambda name: baselines[name]["combined_skill"],
        )
        advantage = (
            candidate_metrics["combined_skill"]
            - baselines[best_name]["combined_skill"]
        )
        rows.append(
            {
                "role": role,
                "rows": int(X.shape[0]),
                "features": int(X.shape[1]),
                "candidate": candidate_metrics,
                "baselines": baselines,
                "best_baseline": best_name,
                "advantage_vs_best": float(advantage),
                "candidate_wins": bool(advantage > 0.0),
                "diagnostics": candidate.diagnostics,
                "elapsed_seconds": float(time.perf_counter() - item_started),
            }
        )
    candidate_auc = [row["candidate"]["roc_auc"] for row in rows]
    candidate_ap_skill = [row["candidate"]["ap_skill"] for row in rows]
    candidate_combined = [row["candidate"]["combined_skill"] for row in rows]
    advantages = [row["advantage_vs_best"] for row in rows]
    baseline_names = sorted(rows[0]["baselines"])
    baseline_means = {
        name: {
            metric: float(
                np.mean([row["baselines"][name][metric] for row in rows])
            )
            for metric in ("roc_auc", "ap_skill", "combined_skill")
        }
        for name in baseline_names
    }
    summary = {
        "dataset_count": len(rows),
        "finite_all": bool(
            all(
                math.isfinite(row["candidate"]["combined_skill"])
                and bool(row["diagnostics"]["finite"])
                for row in rows
            )
        ),
        "candidate_mean_roc_auc": float(np.mean(candidate_auc)),
        "candidate_min_roc_auc": float(np.min(candidate_auc)),
        "candidate_mean_ap_skill": float(np.mean(candidate_ap_skill)),
        "candidate_mean_combined_skill": float(np.mean(candidate_combined)),
        "best_baseline_mean_combined_skill": float(
            max(value["combined_skill"] for value in baseline_means.values())
        ),
        "baseline_means": baseline_means,
        "mean_advantage_vs_best": float(np.mean(advantages)),
        "worst_advantage_vs_best": float(np.min(advantages)),
        "wins_vs_best": int(sum(row["candidate_wins"] for row in rows)),
        "total_elapsed_seconds": float(time.perf_counter() - started),
    }
    return {
        "schema": "data-science-god-level/unsupervised-anomaly-benchmark/1",
        "manifest": manifest,
        "datasets": rows,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    report = run(manifest)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    Path(args.output).write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
