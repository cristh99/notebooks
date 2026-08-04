from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_curve
from sklearn.model_selection import GroupKFold

from .panel import FEATURE_COLUMNS, MONOTONIC_DIRECTIONS

RANDOM_SEED = 20260803
FALSE_NEGATIVE_COST = 100.0
FALSE_POSITIVE_COST = 1.0
CALIBRATION_BINS = 10
BOOTSTRAP_REPLICATES = 5000

BASELINES = (
    "CONSTANT_RATE",
    "CAMELS_LITE",
    "LOGISTIC_L2",
    "SURVIVAL_LOGIT",
)
CHALLENGERS = (
    "MONOTONIC_HGB",
    "MONOTONIC_HGB_HORIZON",
    "CALIBRATED_ENSEMBLE",
)


@dataclass(frozen=True)
class TransformState:
    lower: dict[str, float]
    upper: dict[str, float]
    median: dict[str, float]
    mean: dict[str, float]
    scale: dict[str, float]
    output_columns: tuple[str, ...]
    monotonic_constraints: tuple[int, ...]


@dataclass(frozen=True)
class ModelBundle:
    transformer: TransformState
    models: dict[str, Any]
    constant_rate: float
    camels_calibrator: LogisticRegression
    ensemble_calibrator: LogisticRegression


def fit_transform_state(train: pd.DataFrame) -> TransformState:
    lower: dict[str, float] = {}
    upper: dict[str, float] = {}
    median: dict[str, float] = {}
    mean: dict[str, float] = {}
    scale: dict[str, float] = {}
    for column in FEATURE_COLUMNS:
        values = pd.to_numeric(train[column], errors="coerce")
        finite = values[np.isfinite(values)]
        low = float(finite.quantile(0.005)) if len(finite) else 0.0
        high = float(finite.quantile(0.995)) if len(finite) else 0.0
        if low > high:
            low, high = high, low
        clipped = values.clip(lower=low, upper=high)
        med = float(clipped.median()) if clipped.notna().any() else 0.0
        filled = clipped.fillna(med)
        location = float(filled.mean())
        dispersion = float(filled.std(ddof=0))
        if not np.isfinite(dispersion) or dispersion <= 1e-12:
            dispersion = 1.0
        lower[column] = low
        upper[column] = high
        median[column] = med
        mean[column] = location
        scale[column] = dispersion
    output_columns = tuple(FEATURE_COLUMNS) + tuple(
        f"missing__{column}" for column in FEATURE_COLUMNS
    )
    monotonic = tuple(MONOTONIC_DIRECTIONS[column] for column in FEATURE_COLUMNS) + tuple(
        0 for _ in FEATURE_COLUMNS
    )
    return TransformState(
        lower=lower,
        upper=upper,
        median=median,
        mean=mean,
        scale=scale,
        output_columns=output_columns,
        monotonic_constraints=monotonic,
    )


def transform(frame: pd.DataFrame, state: TransformState) -> pd.DataFrame:
    output: dict[str, np.ndarray] = {}
    for column in FEATURE_COLUMNS:
        values = pd.to_numeric(frame[column], errors="coerce")
        missing = values.isna().to_numpy(dtype=float)
        clipped = values.clip(
            lower=state.lower[column], upper=state.upper[column]
        ).fillna(state.median[column])
        output[column] = (
            (clipped.to_numpy(dtype=float) - state.mean[column])
            / state.scale[column]
        )
        output[f"missing__{column}"] = missing
    return pd.DataFrame(output, index=frame.index)[list(state.output_columns)]


def balanced_weights(labels: np.ndarray) -> np.ndarray:
    labels = np.asarray(labels, dtype=int)
    positives = max(int(labels.sum()), 1)
    negatives = max(int(len(labels) - labels.sum()), 1)
    weights = np.where(
        labels == 1,
        len(labels) / (2.0 * positives),
        len(labels) / (2.0 * negatives),
    )
    return weights.astype(float)


def horizon_weights(labels: np.ndarray, days: np.ndarray) -> np.ndarray:
    weights = balanced_weights(labels)
    days = np.asarray(days, dtype=float)
    closeness = np.where(
        np.asarray(labels, dtype=int) == 1,
        1.0 + np.clip((730.0 - np.nan_to_num(days, nan=730.0)) / 730.0, 0.0, 1.0),
        1.0,
    )
    return weights * closeness


def logistic_model() -> LogisticRegression:
    return LogisticRegression(
        C=1.0,
        penalty="l2",
        solver="lbfgs",
        max_iter=2000,
        random_state=RANDOM_SEED,
    )


def hgb_model(monotonic: Sequence[int]) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=200,
        max_depth=3,
        learning_rate=0.05,
        min_samples_leaf=50,
        l2_regularization=1.0,
        monotonic_cst=list(monotonic),
        random_state=RANDOM_SEED,
    )


def camels_score(frame: pd.DataFrame) -> np.ndarray:
    def value(column: str) -> np.ndarray:
        return pd.to_numeric(frame[column], errors="coerce").fillna(0.0).to_numpy(dtype=float)

    return (
        -value("equity_assets")
        + value("noncurrent_loans_ratio")
        + value("nonperforming_assets_ratio")
        + value("net_chargeoff_proxy")
        - value("roa")
        - value("net_interest_margin")
        + value("wholesale_funding_assets")
        + value("absolute_asset_growth")
        + value("deposit_runoff")
        + value("negative_income")
        + value("declining_capital")
    )


def logit(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped))


def out_of_fold_ensemble(
    x: pd.DataFrame,
    labels: np.ndarray,
    days: np.ndarray,
    groups: np.ndarray,
    monotonic: Sequence[int],
) -> tuple[np.ndarray, LogisticRegression]:
    unique_groups = len(np.unique(groups))
    folds = min(5, unique_groups)
    if folds < 2:
        raise ValueError("not enough bank entities for grouped calibration")
    splitter = GroupKFold(n_splits=folds)
    oof = np.zeros(len(labels), dtype=float)
    for train_index, validation_index in splitter.split(x, labels, groups):
        logistic = logistic_model()
        boosting = hgb_model(monotonic)
        logistic.fit(
            x.iloc[train_index],
            labels[train_index],
            sample_weight=horizon_weights(labels[train_index], days[train_index]),
        )
        boosting.fit(
            x.iloc[train_index],
            labels[train_index],
            sample_weight=balanced_weights(labels[train_index]),
        )
        raw = 0.5 * logistic.predict_proba(x.iloc[validation_index])[:, 1] + 0.5 * boosting.predict_proba(x.iloc[validation_index])[:, 1]
        oof[validation_index] = raw
    calibrator = LogisticRegression(
        C=1e6,
        penalty="l2",
        solver="lbfgs",
        max_iter=1000,
        random_state=RANDOM_SEED,
    )
    calibrator.fit(
        logit(oof).reshape(-1, 1),
        labels,
        sample_weight=balanced_weights(labels),
    )
    return oof, calibrator


def train_models(train: pd.DataFrame) -> ModelBundle:
    state = fit_transform_state(train)
    x = transform(train, state)
    y = train["label"].to_numpy(dtype=int)
    days = train["days_to_failure"].to_numpy(dtype=float)
    groups = train["CERT"].to_numpy()

    camels = LogisticRegression(
        C=1e6,
        penalty="l2",
        solver="lbfgs",
        max_iter=1000,
        random_state=RANDOM_SEED,
    )
    camels.fit(
        camels_score(train).reshape(-1, 1),
        y,
        sample_weight=balanced_weights(y),
    )

    models: dict[str, Any] = {}
    models["LOGISTIC_L2"] = logistic_model()
    models["LOGISTIC_L2"].fit(x, y, sample_weight=balanced_weights(y))
    models["SURVIVAL_LOGIT"] = logistic_model()
    models["SURVIVAL_LOGIT"].fit(
        x, y, sample_weight=horizon_weights(y, days)
    )
    models["MONOTONIC_HGB"] = hgb_model(state.monotonic_constraints)
    models["MONOTONIC_HGB"].fit(x, y, sample_weight=balanced_weights(y))
    models["MONOTONIC_HGB_HORIZON"] = hgb_model(state.monotonic_constraints)
    models["MONOTONIC_HGB_HORIZON"].fit(
        x, y, sample_weight=horizon_weights(y, days)
    )
    _, calibrator = out_of_fold_ensemble(
        x, y, days, groups, state.monotonic_constraints
    )
    return ModelBundle(
        transformer=state,
        models=models,
        constant_rate=float(y.mean()),
        camels_calibrator=camels,
        ensemble_calibrator=calibrator,
    )


def predict(bundle: ModelBundle, frame: pd.DataFrame) -> dict[str, np.ndarray]:
    x = transform(frame, bundle.transformer)
    predictions: dict[str, np.ndarray] = {
        "CONSTANT_RATE": np.full(len(frame), bundle.constant_rate, dtype=float),
        "CAMELS_LITE": bundle.camels_calibrator.predict_proba(
            camels_score(frame).reshape(-1, 1)
        )[:, 1],
    }
    for name, model in bundle.models.items():
        predictions[name] = model.predict_proba(x)[:, 1]
    ensemble_raw = 0.5 * predictions["SURVIVAL_LOGIT"] + 0.5 * predictions["MONOTONIC_HGB"]
    predictions["CALIBRATED_ENSEMBLE"] = bundle.ensemble_calibrator.predict_proba(
        logit(ensemble_raw).reshape(-1, 1)
    )[:, 1]
    return predictions


def threshold_candidates(probabilities: np.ndarray) -> np.ndarray:
    values = np.asarray(probabilities, dtype=float)
    quantiles = np.linspace(0.0, 1.0, 1001)
    return np.unique(np.concatenate(([0.0, 1.0], np.quantile(values, quantiles))))


def cost_at_threshold(
    labels: np.ndarray,
    probabilities: np.ndarray,
    threshold: float,
) -> dict[str, float | int]:
    predicted = np.asarray(probabilities) >= threshold
    labels = np.asarray(labels, dtype=int)
    false_negatives = int(((labels == 1) & ~predicted).sum())
    false_positives = int(((labels == 0) & predicted).sum())
    cost = FALSE_NEGATIVE_COST * false_negatives + FALSE_POSITIVE_COST * false_positives
    return {
        "threshold": float(threshold),
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "total_cost": float(cost),
        "cost_per_row": float(cost / max(len(labels), 1)),
    }


def select_threshold(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float | int]:
    candidates = threshold_candidates(probabilities)
    results = [cost_at_threshold(labels, probabilities, value) for value in candidates]
    return min(
        results,
        key=lambda item: (
            float(item["total_cost"]),
            int(item["false_negatives"]),
            int(item["false_positives"]),
            -float(item["threshold"]),
        ),
    )


def recall_at_fpr(labels: np.ndarray, probabilities: np.ndarray, limit: float) -> float:
    fpr, tpr, _ = roc_curve(labels, probabilities)
    eligible = tpr[fpr <= limit + 1e-12]
    return float(np.max(eligible)) if len(eligible) else 0.0


def top_precision(labels: np.ndarray, probabilities: np.ndarray, fraction: float) -> float:
    count = max(1, int(np.ceil(len(labels) * fraction)))
    order = np.argsort(-np.asarray(probabilities, dtype=float), kind="mergesort")[:count]
    return float(np.mean(np.asarray(labels, dtype=int)[order]))


def calibration_error(labels: np.ndarray, probabilities: np.ndarray, bins: int = CALIBRATION_BINS) -> float:
    labels = np.asarray(labels, dtype=int)
    probabilities = np.asarray(probabilities, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(labels)
    error = 0.0
    for index in range(bins):
        lower = edges[index]
        upper = edges[index + 1]
        mask = (
            (probabilities >= lower)
            & (probabilities < upper if index < bins - 1 else probabilities <= upper)
        )
        if not mask.any():
            continue
        error += float(mask.mean()) * abs(
            float(labels[mask].mean()) - float(probabilities[mask].mean())
        )
    return error if total else 0.0


def performance_metrics(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    labels = frame["label"].to_numpy(dtype=int)
    cost = cost_at_threshold(labels, probabilities, threshold)
    predicted = np.asarray(probabilities) >= threshold
    positives = labels == 1
    lead_days = frame.loc[positives & predicted, "days_to_failure"].to_numpy(dtype=float)
    return {
        "rows": int(len(frame)),
        "positive_rows": int(labels.sum()),
        "positive_entities": int(frame.loc[frame["label"] == 1, "CERT"].nunique()),
        "average_precision": float(average_precision_score(labels, probabilities)),
        "recall_at_fpr_0_005": recall_at_fpr(labels, probabilities, 0.005),
        "recall_at_fpr_0_01": recall_at_fpr(labels, probabilities, 0.01),
        "recall_at_fpr_0_02": recall_at_fpr(labels, probabilities, 0.02),
        "top_1pct_precision": top_precision(labels, probabilities, 0.01),
        "top_2pct_precision": top_precision(labels, probabilities, 0.02),
        "brier": float(brier_score_loss(labels, probabilities)),
        "calibration_error_10bin": calibration_error(labels, probabilities),
        "threshold": float(threshold),
        "false_negatives": cost["false_negatives"],
        "false_positives": cost["false_positives"],
        "total_cost": cost["total_cost"],
        "cost_per_row": cost["cost_per_row"],
        "median_lead_days_detected": float(np.median(lead_days)) if len(lead_days) else None,
    }


def method_selection_key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, float, str]:
    name, metrics = item
    return (
        float(metrics["cost_per_row"]),
        -float(metrics["average_precision"]),
        float(metrics["brier"]),
        name,
    )


def select_method(metrics: Mapping[str, dict[str, Any]], methods: Sequence[str]) -> str:
    return min(((name, metrics[name]) for name in methods), key=method_selection_key)[0]


def lcg_indices(seed: int, count: int, modulus: int) -> list[int]:
    state = seed & 0xFFFFFFFF
    output: list[int] = []
    for _ in range(count):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        output.append(state % modulus)
    return output


def bank_cluster_bootstrap(
    frame: pd.DataFrame,
    baseline_probability: np.ndarray,
    challenger_probability: np.ndarray,
    baseline_threshold: float,
    challenger_threshold: float,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    working = frame[["CERT", "label"]].copy()
    working["baseline"] = np.asarray(baseline_probability) >= baseline_threshold
    working["challenger"] = np.asarray(challenger_probability) >= challenger_threshold
    entity_improvement: list[float] = []
    for _, group in working.groupby("CERT", sort=True):
        labels = group["label"].to_numpy(dtype=int)
        baseline_pred = group["baseline"].to_numpy(dtype=bool)
        challenger_pred = group["challenger"].to_numpy(dtype=bool)
        baseline_cost = FALSE_NEGATIVE_COST * int(((labels == 1) & ~baseline_pred).sum()) + FALSE_POSITIVE_COST * int(((labels == 0) & baseline_pred).sum())
        challenger_cost = FALSE_NEGATIVE_COST * int(((labels == 1) & ~challenger_pred).sum()) + FALSE_POSITIVE_COST * int(((labels == 0) & challenger_pred).sum())
        entity_improvement.append(float(baseline_cost - challenger_cost))
    values = np.asarray(entity_improvement, dtype=float)
    if len(values) == 0:
        return {"entities": 0, "mean_improvement": None, "lower_95": None, "upper_95": None, "replicates": 0, "seed": RANDOM_SEED}
    indices = lcg_indices(RANDOM_SEED, replicates * len(values), len(values))
    means: list[float] = []
    cursor = 0
    for _ in range(replicates):
        total = 0.0
        for _ in range(len(values)):
            total += values[indices[cursor]]
            cursor += 1
        means.append(total / len(values))
    ordered = np.sort(np.asarray(means, dtype=float))
    return {
        "entities": int(len(values)),
        "mean_improvement": float(values.mean()),
        "lower_95": float(ordered[int(np.floor(0.025 * (replicates - 1)))]),
        "upper_95": float(ordered[int(np.ceil(0.975 * (replicates - 1)))]),
        "replicates": replicates,
        "seed": RANDOM_SEED,
    }
