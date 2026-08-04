from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.optimize import nnls
from sklearn.base import clone
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import balanced_accuracy_score, mean_squared_error
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler

Task = Literal["classification", "regression"]


@dataclass(frozen=True)
class PredictionResult:
    predictions: np.ndarray
    probabilities: np.ndarray | None
    selected_models: tuple[str, ...]
    validation_score: float


def _finite_matrix(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("X must be a 2D array")
    arr = arr.copy()
    arr[~np.isfinite(arr)] = np.nan
    return arr


def _classification_models(n_samples: int, n_features: int, seed: int):
    leaf = 1 if n_samples >= 300 else 2
    max_features = 1.0 if n_features <= 12 else "sqrt"
    return {
        "extra_trees": make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesClassifier(
                n_estimators=360,
                min_samples_leaf=leaf,
                max_features=max_features,
                class_weight="balanced",
                random_state=seed,
                n_jobs=-1,
            ),
        ),
        "hist_gbdt": make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(
                learning_rate=0.055,
                max_iter=240,
                max_leaf_nodes=31,
                min_samples_leaf=max(10, min(30, n_samples // 50)),
                l2_regularization=1.0,
                random_state=seed,
            ),
        ),
        "random_forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=leaf,
                max_features="sqrt",
                class_weight="balanced_subsample",
                random_state=seed + 1,
                n_jobs=-1,
            ),
        ),
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
    }


def _regression_models(n_samples: int, n_features: int, seed: int):
    leaf = 1 if n_samples >= 500 else 2
    max_features = 1.0 if n_features <= 20 else 0.75
    return {
        "extra_trees": make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesRegressor(
                n_estimators=360,
                min_samples_leaf=leaf,
                max_features=max_features,
                random_state=seed,
                n_jobs=-1,
            ),
        ),
        "hist_gbdt": make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingRegressor(
                learning_rate=0.055,
                max_iter=260,
                max_leaf_nodes=31,
                min_samples_leaf=max(10, min(30, n_samples // 50)),
                l2_regularization=1.0,
                random_state=seed,
            ),
        ),
        "random_forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestRegressor(
                n_estimators=300,
                min_samples_leaf=leaf,
                max_features=max_features,
                random_state=seed + 1,
                n_jobs=-1,
            ),
        ),
        "ridge": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            TransformedTargetRegressor(
                regressor=Ridge(alpha=1.0),
                transformer=StandardScaler(),
            ),
        ),
    }


def _safe_class_probabilities(model, x: np.ndarray, classes: np.ndarray) -> np.ndarray:
    probs = np.asarray(model.predict_proba(x), dtype=np.float64)
    fitted_classes = np.asarray(model.classes_)
    if hasattr(model, "steps"):
        fitted_classes = np.asarray(model.steps[-1][1].classes_)
    aligned = np.zeros((len(x), len(classes)), dtype=np.float64)
    for local_idx, label in enumerate(fitted_classes):
        global_idx = int(np.flatnonzero(classes == label)[0])
        aligned[:, global_idx] = probs[:, local_idx]
    aligned = np.clip(aligned, 1e-12, None)
    aligned /= aligned.sum(axis=1, keepdims=True)
    return aligned


def _fit_classification(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    seed: int,
) -> PredictionResult:
    encoder = LabelEncoder()
    y = encoder.fit_transform(np.asarray(y_train))
    classes = np.arange(len(encoder.classes_))
    if len(classes) < 2:
        pred = np.repeat(encoder.classes_[0], len(x_test))
        return PredictionResult(pred, np.ones((len(x_test), 1)), ("constant",), 1.0)

    models = _classification_models(len(y), x_train.shape[1], seed)
    min_class = int(np.bincount(y).min())
    splits = max(2, min(4, min_class))
    cv = StratifiedKFold(n_splits=splits, shuffle=True, random_state=seed)
    oof = {name: np.zeros((len(y), len(classes)), dtype=np.float64) for name in models}
    scores: dict[str, float] = {}

    for name, prototype in models.items():
        for train_idx, valid_idx in cv.split(x_train, y):
            model = clone(prototype)
            model.fit(x_train[train_idx], y[train_idx])
            oof[name][valid_idx] = _safe_class_probabilities(model, x_train[valid_idx], classes)
        scores[name] = balanced_accuracy_score(y, oof[name].argmax(axis=1))

    ranked = sorted(scores, key=lambda name: (-scores[name], name))
    selected = tuple(ranked[: min(3, len(ranked))])
    floor = 1.0 / len(classes)
    raw_weights = np.array([max(scores[name] - floor, 0.01) ** 2 for name in selected])
    weights = raw_weights / raw_weights.sum()

    test_prob = np.zeros((len(x_test), len(classes)), dtype=np.float64)
    for weight, name in zip(weights, selected):
        model = clone(models[name])
        model.fit(x_train, y)
        test_prob += weight * _safe_class_probabilities(model, x_test, classes)
    test_prob = np.clip(test_prob, 1e-12, None)
    test_prob /= test_prob.sum(axis=1, keepdims=True)
    encoded = test_prob.argmax(axis=1)
    predictions = encoder.inverse_transform(encoded)
    validation = float(sum(weights[i] * scores[name] for i, name in enumerate(selected)))
    return PredictionResult(predictions, test_prob, selected, validation)


def _fit_regression(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    seed: int,
) -> PredictionResult:
    y = np.asarray(y_train, dtype=np.float64)
    if y.ndim != 1:
        y = y.reshape(-1)
    if not np.isfinite(y).all():
        raise ValueError("regression target must be finite")
    if np.std(y) == 0:
        pred = np.repeat(float(np.mean(y)), len(x_test))
        return PredictionResult(pred, None, ("constant",), 0.0)

    models = _regression_models(len(y), x_train.shape[1], seed)
    splits = 4 if len(y) >= 400 else 3
    cv = KFold(n_splits=splits, shuffle=True, random_state=seed)
    names = tuple(sorted(models))
    oof = np.zeros((len(y), len(names)), dtype=np.float64)

    for col, name in enumerate(names):
        prototype = models[name]
        for train_idx, valid_idx in cv.split(x_train):
            model = clone(prototype)
            model.fit(x_train[train_idx], y[train_idx])
            oof[valid_idx, col] = model.predict(x_train[valid_idx])

    centered = y - float(np.mean(y))
    design = oof - float(np.mean(y))
    weights, _ = nnls(design, centered)
    if float(weights.sum()) <= 1e-12:
        rmses = np.sqrt(np.mean((oof - y[:, None]) ** 2, axis=0))
        best = int(np.argmin(rmses))
        weights = np.zeros(len(names), dtype=np.float64)
        weights[best] = 1.0
    else:
        weights /= weights.sum()

    active = np.flatnonzero(weights >= 0.05)
    if len(active) == 0:
        active = np.array([int(np.argmax(weights))])
    active_weights = weights[active]
    active_weights /= active_weights.sum()
    selected = tuple(names[index] for index in active)

    test_pred = np.zeros(len(x_test), dtype=np.float64)
    for weight, index in zip(active_weights, active):
        model = clone(models[names[index]])
        model.fit(x_train, y)
        test_pred += weight * np.asarray(model.predict(x_test), dtype=np.float64)

    oof_blend = oof[:, active] @ active_weights
    nrmse = float(np.sqrt(mean_squared_error(y, oof_blend)) / max(np.std(y), 1e-12))
    return PredictionResult(test_pred, None, selected, -nrmse)


def fit_predict(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    task: Task,
    seed: int = 1729,
) -> PredictionResult:
    x_train_f = _finite_matrix(x_train)
    x_test_f = _finite_matrix(x_test)
    if x_train_f.shape[1] != x_test_f.shape[1]:
        raise ValueError("train/test feature mismatch")
    if len(x_train_f) != len(y_train):
        raise ValueError("X/y length mismatch")
    if task == "classification":
        return _fit_classification(x_train_f, np.asarray(y_train), x_test_f, seed)
    if task == "regression":
        return _fit_regression(x_train_f, np.asarray(y_train), x_test_f, seed)
    raise ValueError(f"unknown task: {task}")
