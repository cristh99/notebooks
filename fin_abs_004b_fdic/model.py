from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from fin_abs_004_fdic.model import (
    TransformState,
    balanced_weights,
    bank_cluster_bootstrap,
    camels_score,
    fit_transform_state,
    hgb_model,
    horizon_weights,
    logistic_model,
    logit,
    performance_metrics,
    select_method,
    select_threshold,
    transform,
)

RANDOM_SEED = 20260804
CALIBRATION_SPLIT_SEED = "FIN-ABS-004B-CALIBRATION-SPLIT-V1"
DEFAULT_RF_TREES = 600

BASELINES = (
    "CONSTANT_RATE",
    "CAMELS_LITE",
    "LOGISTIC_L2",
    "SURVIVAL_LOGIT",
    "LOGISTIC_L2_PLATT",
    "SURVIVAL_LOGIT_PLATT",
    "RF_BALANCED",
    "RF_COST_SENSITIVE",
    "RF_BALANCED_PLATT",
    "RF_COST_PLATT",
)
CHALLENGERS = (
    "MONOTONIC_HGB_HORIZON",
    "MONOTONIC_HGB_HORIZON_PLATT",
    "RF_HGB_PLATT",
    "LOGIT_RF_HGB_PLATT",
)


@dataclass(frozen=True)
class ExtendedBundle:
    transformer: TransformState
    models: dict[str, Any]
    constant_rate: float
    camels_calibrator: LogisticRegression
    calibrators: dict[str, LogisticRegression]


def entity_calibration_bucket(cert: int) -> int:
    value = hashlib.sha256(
        f"{CALIBRATION_SPLIT_SEED}|{int(cert)}".encode("utf-8")
    ).hexdigest()
    return int(value[:16], 16) % 100


def split_validation_entities(
    validation: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    working = validation.copy()
    working["calibration_bucket"] = working["CERT"].map(entity_calibration_bucket)
    calibration = working.loc[working["calibration_bucket"] < 50].copy()
    selection = working.loc[working["calibration_bucket"] >= 50].copy()
    calibration_entities = set(calibration["CERT"].astype(int))
    selection_entities = set(selection["CERT"].astype(int))
    report = {
        "seed": CALIBRATION_SPLIT_SEED,
        "bucket_rule": {"calibration": [0, 49], "selection": [50, 99]},
        "calibration_rows": int(len(calibration)),
        "selection_rows": int(len(selection)),
        "calibration_entities": int(len(calibration_entities)),
        "selection_entities": int(len(selection_entities)),
        "calibration_positive_rows": int(calibration["label"].sum()),
        "selection_positive_rows": int(selection["label"].sum()),
        "calibration_positive_entities": int(
            calibration.loc[calibration["label"] == 1, "CERT"].nunique()
        ),
        "selection_positive_entities": int(
            selection.loc[selection["label"] == 1, "CERT"].nunique()
        ),
        "entity_overlap": int(len(calibration_entities & selection_entities)),
    }
    if min(
        report["calibration_positive_entities"],
        report["selection_positive_entities"],
    ) < 5:
        raise ValueError("validation calibration split has insufficient positive entities")
    if report["entity_overlap"] != 0:
        raise ValueError("calibration and selection entities overlap")
    return calibration, selection, report


def random_forest_model(
    *, cost_sensitive: bool, n_estimators: int = DEFAULT_RF_TREES
) -> RandomForestClassifier:
    class_weight: str | dict[int, float]
    class_weight = {0: 1.0, 1: 100.0} if cost_sensitive else "balanced_subsample"
    return RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=None,
        min_samples_leaf=20,
        max_features="sqrt",
        bootstrap=True,
        class_weight=class_weight,
        n_jobs=-1,
        random_state=RANDOM_SEED,
    )


def platt_model() -> LogisticRegression:
    return LogisticRegression(
        C=1e6,
        penalty="l2",
        solver="lbfgs",
        max_iter=2000,
        random_state=RANDOM_SEED,
    )


def _fit_platt(raw: np.ndarray, labels: np.ndarray) -> LogisticRegression:
    """Calibrate to observed prevalence; class weights would distort PD levels."""
    calibrator = platt_model()
    calibrator.fit(logit(raw).reshape(-1, 1), labels)
    return calibrator


def _apply_platt(calibrator: LogisticRegression, raw: np.ndarray) -> np.ndarray:
    return calibrator.predict_proba(logit(raw).reshape(-1, 1))[:, 1]


def train_models(
    train: pd.DataFrame, *, rf_trees: int = DEFAULT_RF_TREES
) -> ExtendedBundle:
    state = fit_transform_state(train)
    x = transform(train, state)
    y = train["label"].to_numpy(dtype=int)
    days = train["days_to_failure"].to_numpy(dtype=float)

    camels = platt_model()
    camels.fit(camels_score(train).reshape(-1, 1), y)

    models: dict[str, Any] = {}
    models["LOGISTIC_L2"] = logistic_model()
    models["LOGISTIC_L2"].fit(x, y, sample_weight=balanced_weights(y))
    models["SURVIVAL_LOGIT"] = logistic_model()
    models["SURVIVAL_LOGIT"].fit(
        x, y, sample_weight=horizon_weights(y, days)
    )
    models["MONOTONIC_HGB_HORIZON"] = hgb_model(state.monotonic_constraints)
    models["MONOTONIC_HGB_HORIZON"].fit(
        x, y, sample_weight=horizon_weights(y, days)
    )
    models["RF_BALANCED"] = random_forest_model(
        cost_sensitive=False, n_estimators=rf_trees
    )
    models["RF_BALANCED"].fit(x, y)
    models["RF_COST_SENSITIVE"] = random_forest_model(
        cost_sensitive=True, n_estimators=rf_trees
    )
    models["RF_COST_SENSITIVE"].fit(x, y)
    return ExtendedBundle(
        transformer=state,
        models=models,
        constant_rate=float(y.mean()),
        camels_calibrator=camels,
        calibrators={},
    )


def raw_predictions(
    bundle: ExtendedBundle, frame: pd.DataFrame
) -> dict[str, np.ndarray]:
    x = transform(frame, bundle.transformer)
    predictions: dict[str, np.ndarray] = {
        "CONSTANT_RATE": np.full(len(frame), bundle.constant_rate, dtype=float),
        "CAMELS_LITE": bundle.camels_calibrator.predict_proba(
            camels_score(frame).reshape(-1, 1)
        )[:, 1],
    }
    for name, model in bundle.models.items():
        predictions[name] = model.predict_proba(x)[:, 1]
    return predictions


def fit_calibrators(
    bundle: ExtendedBundle, calibration: pd.DataFrame
) -> ExtendedBundle:
    raw = raw_predictions(bundle, calibration)
    labels = calibration["label"].to_numpy(dtype=int)
    mixtures = {
        "LOGISTIC_L2_PLATT": raw["LOGISTIC_L2"],
        "SURVIVAL_LOGIT_PLATT": raw["SURVIVAL_LOGIT"],
        "RF_BALANCED_PLATT": raw["RF_BALANCED"],
        "RF_COST_PLATT": raw["RF_COST_SENSITIVE"],
        "MONOTONIC_HGB_HORIZON_PLATT": raw["MONOTONIC_HGB_HORIZON"],
        "RF_HGB_PLATT": (
            raw["RF_BALANCED"] + raw["MONOTONIC_HGB_HORIZON"]
        )
        / 2.0,
        "LOGIT_RF_HGB_PLATT": (
            raw["SURVIVAL_LOGIT"]
            + raw["RF_BALANCED"]
            + raw["MONOTONIC_HGB_HORIZON"]
        )
        / 3.0,
    }
    calibrators = {
        name: _fit_platt(values, labels) for name, values in mixtures.items()
    }
    return replace(bundle, calibrators=calibrators)


def predict(bundle: ExtendedBundle, frame: pd.DataFrame) -> dict[str, np.ndarray]:
    expected_calibrators = {
        "LOGISTIC_L2_PLATT",
        "SURVIVAL_LOGIT_PLATT",
        "RF_BALANCED_PLATT",
        "RF_COST_PLATT",
        "MONOTONIC_HGB_HORIZON_PLATT",
        "RF_HGB_PLATT",
        "LOGIT_RF_HGB_PLATT",
    }
    if set(bundle.calibrators) != expected_calibrators:
        raise ValueError("all preregistered calibrators must be fitted before prediction")
    raw = raw_predictions(bundle, frame)
    direct = {
        "LOGISTIC_L2_PLATT": "LOGISTIC_L2",
        "SURVIVAL_LOGIT_PLATT": "SURVIVAL_LOGIT",
        "RF_BALANCED_PLATT": "RF_BALANCED",
        "RF_COST_PLATT": "RF_COST_SENSITIVE",
        "MONOTONIC_HGB_HORIZON_PLATT": "MONOTONIC_HGB_HORIZON",
    }
    for calibrated_name, raw_name in direct.items():
        raw[calibrated_name] = _apply_platt(
            bundle.calibrators[calibrated_name], raw[raw_name]
        )
    rf_hgb = (
        raw["RF_BALANCED"] + raw["MONOTONIC_HGB_HORIZON"]
    ) / 2.0
    raw["RF_HGB_PLATT"] = _apply_platt(
        bundle.calibrators["RF_HGB_PLATT"], rf_hgb
    )
    tri = (
        raw["SURVIVAL_LOGIT"]
        + raw["RF_BALANCED"]
        + raw["MONOTONIC_HGB_HORIZON"]
    ) / 3.0
    raw["LOGIT_RF_HGB_PLATT"] = _apply_platt(
        bundle.calibrators["LOGIT_RF_HGB_PLATT"], tri
    )
    return {name: raw[name] for name in (*BASELINES, *CHALLENGERS)}


def calibration_parameters(bundle: ExtendedBundle) -> dict[str, dict[str, float]]:
    return {
        name: {
            "coefficient": float(model.coef_[0, 0]),
            "intercept": float(model.intercept_[0]),
        }
        for name, model in sorted(bundle.calibrators.items())
    }


__all__ = [
    "BASELINES",
    "CHALLENGERS",
    "ExtendedBundle",
    "bank_cluster_bootstrap",
    "calibration_parameters",
    "entity_calibration_bucket",
    "fit_calibrators",
    "performance_metrics",
    "predict",
    "random_forest_model",
    "select_method",
    "select_threshold",
    "split_validation_entities",
    "train_models",
]
