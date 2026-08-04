from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import balanced_accuracy_score, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler

from estimator import fit_predict


def _read(path: Path) -> tuple[np.ndarray, np.ndarray]:
    frame = pd.read_csv(path, sep="\t", compression="gzip")
    if "target" not in frame.columns:
        raise ValueError(f"missing target: {path}")
    y = frame.pop("target").to_numpy()
    x = frame.to_numpy(dtype=np.float64)
    return x, y


def _classification_baselines(x_train, y_train, x_test, seed):
    encoder = LabelEncoder()
    y = encoder.fit_transform(y_train)
    models = {
        "logistic": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(
                C=1.0,
                max_iter=2500,
                class_weight="balanced",
                solver="lbfgs",
                random_state=seed,
            ),
        ),
        "random_forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=1 if len(y) >= 300 else 2,
                max_features="sqrt",
                class_weight="balanced_subsample",
                random_state=seed,
                n_jobs=-1,
            ),
        ),
    }
    output = {}
    for name, model in models.items():
        model.fit(x_train, y)
        output[name] = encoder.inverse_transform(model.predict(x_test))
    return output


def _regression_baselines(x_train, y_train, x_test, seed):
    models = {
        "ridge": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            TransformedTargetRegressor(
                regressor=Ridge(alpha=1.0),
                transformer=StandardScaler(),
            ),
        ),
        "random_forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestRegressor(
                n_estimators=300,
                min_samples_leaf=1 if len(y_train) >= 500 else 2,
                max_features=1.0 if x_train.shape[1] <= 20 else 0.75,
                random_state=seed,
                n_jobs=-1,
            ),
        ),
    }
    output = {}
    for name, model in models.items():
        model.fit(x_train, y_train)
        output[name] = np.asarray(model.predict(x_test), dtype=np.float64)
    return output


def _classification_score(y_true, y_pred) -> dict[str, float]:
    labels = np.unique(y_true)
    raw = float(balanced_accuracy_score(y_true, y_pred))
    chance = 1.0 / max(len(labels), 1)
    normalized = (raw - chance) / max(1.0 - chance, 1e-12)
    return {"balanced_accuracy": raw, "normalized_score": float(normalized)}


def _regression_score(y_true, y_pred) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    scale = float(np.std(y_true))
    nrmse = rmse / max(scale, 1e-12)
    return {"rmse": rmse, "nrmse": float(nrmse), "normalized_score": float(1.0 - nrmse)}


def evaluate(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for item in manifest["datasets"]:
        path = Path(item["path"])
        task = item["task"]
        seed = int(item["seed"])
        x, y = _read(path)
        stratify = y if task == "classification" else None
        x_train, x_test, y_train, y_test = train_test_split(
            x,
            y,
            test_size=0.30,
            random_state=seed,
            stratify=stratify,
        )
        started = time.perf_counter()
        candidate = fit_predict(x_train, y_train, x_test, task, seed=1729)
        elapsed = time.perf_counter() - started
        if task == "classification":
            candidate_metrics = _classification_score(y_test, candidate.predictions)
            baseline_predictions = _classification_baselines(x_train, y_train, x_test, seed)
            baseline_metrics = {
                name: _classification_score(y_test, prediction)
                for name, prediction in baseline_predictions.items()
            }
        elif task == "regression":
            candidate_metrics = _regression_score(y_test, candidate.predictions)
            baseline_predictions = _regression_baselines(x_train, y_train, x_test, seed)
            baseline_metrics = {
                name: _regression_score(y_test, prediction)
                for name, prediction in baseline_predictions.items()
            }
        else:
            raise ValueError(f"unknown task: {task}")

        best_name = max(
            baseline_metrics,
            key=lambda name: baseline_metrics[name]["normalized_score"],
        )
        best_score = baseline_metrics[best_name]["normalized_score"]
        score = candidate_metrics["normalized_score"]
        row = {
            "role": item["role"],
            "task": task,
            "n_instances": int(len(x)),
            "n_features": int(x.shape[1]),
            "n_classes": int(len(np.unique(y))) if task == "classification" else None,
            "candidate": candidate_metrics,
            "baselines": baseline_metrics,
            "best_baseline": best_name,
            "advantage_vs_best": float(score - best_score),
            "candidate_wins": bool(score > best_score + 1e-9),
            "selected_models": list(candidate.selected_models),
            "internal_validation_score": float(candidate.validation_score),
            "elapsed_seconds": float(elapsed),
            "finite": bool(
                np.isfinite(candidate.predictions).all()
                and all(math.isfinite(value) for value in candidate_metrics.values())
            ),
        }
        rows.append(row)

    classification = [row for row in rows if row["task"] == "classification"]
    regression = [row for row in rows if row["task"] == "regression"]
    summary = {
        "dataset_count": len(rows),
        "classification_count": len(classification),
        "regression_count": len(regression),
        "finite_all": all(row["finite"] for row in rows),
        "candidate_mean_score": float(
            np.mean([row["candidate"]["normalized_score"] for row in rows])
        ),
        "best_baseline_mean_score": float(
            np.mean([
                row["baselines"][row["best_baseline"]]["normalized_score"]
                for row in rows
            ])
        ),
        "mean_advantage_vs_best": float(
            np.mean([row["advantage_vs_best"] for row in rows])
        ),
        "wins_vs_best": int(sum(row["candidate_wins"] for row in rows)),
        "classification_mean_score": float(
            np.mean([row["candidate"]["normalized_score"] for row in classification])
        ),
        "regression_mean_score": float(
            np.mean([row["candidate"]["normalized_score"] for row in regression])
        ),
        "worst_advantage_vs_best": float(min(row["advantage_vs_best"] for row in rows)),
        "total_elapsed_seconds": float(sum(row["elapsed_seconds"] for row in rows)),
    }
    return {
        "schema": "data-science-god-level/tabular-transfer-report/1",
        "manifest": manifest,
        "datasets": rows,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = evaluate(Path(args.manifest))
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    Path(args.output).write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
