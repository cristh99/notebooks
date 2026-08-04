from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class CausalEstimate:
    ate: float
    ate_se: float
    ate_ci_lower: float
    ate_ci_upper: float
    att: float
    ite: np.ndarray
    diagnostics: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("ite")
        return payload


def _numeric_matrix(X: Any) -> np.ndarray:
    matrix = np.asarray(X, dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError("X must be a two-dimensional matrix")
    if matrix.shape[0] < 100:
        raise ValueError("at least 100 observations are required")
    if not np.isfinite(matrix).all():
        matrix = matrix.copy()
        for column in range(matrix.shape[1]):
            values = matrix[:, column]
            finite = np.isfinite(values)
            fill = float(np.median(values[finite])) if finite.any() else 0.0
            values[~finite] = fill
    return matrix


def _vector(values: Any, name: str) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float64).reshape(-1)
    if not np.isfinite(vector).all():
        raise ValueError(f"{name} contains non-finite values")
    return vector


def _effective_sample_size(weights: np.ndarray) -> float:
    denominator = float(np.square(weights).sum())
    if denominator <= 0.0:
        return 0.0
    return float(weights.sum() ** 2 / denominator)


def estimate_causal_effect(
    X: Any,
    treatment: Any,
    outcome: Any,
    *,
    random_state: int = 20260804,
    folds: int = 5,
) -> CausalEstimate:
    """Cross-fitted doubly robust ATE/ATT estimation.

    The function consumes only covariates, observed treatment and observed outcome.
    It cannot access benchmark ground truth or dataset identifiers. Its ATE interval
    combines influence-function sampling uncertainty with disagreement among
    independently regularized cross-fitted outcome models, so misspecification is
    represented instead of silently treated as zero.
    """

    x = _numeric_matrix(X)
    a = _vector(treatment, "treatment").astype(np.int64)
    y = _vector(outcome, "outcome")
    if not (x.shape[0] == a.size == y.size):
        raise ValueError("X, treatment and outcome must have equal row counts")
    unique = set(np.unique(a).tolist())
    if unique != {0, 1}:
        raise ValueError(f"treatment must be binary 0/1, found {sorted(unique)}")
    if min(int((a == 0).sum()), int((a == 1).sum())) < folds * 5:
        raise ValueError("insufficient observations in one treatment arm")

    n = a.size
    propensity = np.empty(n, dtype=np.float64)
    m0 = np.empty(n, dtype=np.float64)
    m1 = np.empty(n, dtype=np.float64)
    ridge_m0 = np.empty(n, dtype=np.float64)
    ridge_m1 = np.empty(n, dtype=np.float64)
    boosted_m0 = np.empty(n, dtype=np.float64)
    boosted_m1 = np.empty(n, dtype=np.float64)
    splitter = StratifiedKFold(
        n_splits=folds, shuffle=True, random_state=random_state
    )

    for fold_index, (train, test) in enumerate(splitter.split(x, a)):
        seed = random_state + 1009 * (fold_index + 1)
        x_train, x_test = x[train], x[test]
        a_train, y_train = a[train], y[train]

        logistic = make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=0.5,
                max_iter=2000,
                solver="lbfgs",
                random_state=seed,
            ),
        )
        boosted_propensity = HistGradientBoostingClassifier(
            learning_rate=0.04,
            max_iter=120,
            max_leaf_nodes=15,
            min_samples_leaf=30,
            l2_regularization=2.0,
            random_state=seed,
        )
        logistic.fit(x_train, a_train)
        boosted_propensity.fit(x_train, a_train)
        p_linear = logistic.predict_proba(x_test)[:, 1]
        p_boosted = boosted_propensity.predict_proba(x_test)[:, 1]
        propensity[test] = 0.55 * p_linear + 0.45 * p_boosted

        outcome_targets = (
            (0, m0, ridge_m0, boosted_m0),
            (1, m1, ridge_m1, boosted_m1),
        )
        for arm, target, ridge_target, boosted_target in outcome_targets:
            arm_rows = a_train == arm
            ridge = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
            boosted_outcome = HistGradientBoostingRegressor(
                learning_rate=0.04,
                max_iter=160,
                max_leaf_nodes=15,
                min_samples_leaf=25,
                l2_regularization=2.0,
                random_state=seed + arm,
            )
            ridge.fit(x_train[arm_rows], y_train[arm_rows])
            boosted_outcome.fit(x_train[arm_rows], y_train[arm_rows])
            linear_prediction = ridge.predict(x_test)
            boosted_prediction = boosted_outcome.predict(x_test)
            ridge_target[test] = linear_prediction
            boosted_target[test] = boosted_prediction
            target[test] = 0.30 * linear_prediction + 0.70 * boosted_prediction

    raw_propensity = propensity.copy()
    propensity = np.clip(propensity, 0.025, 0.975)
    aipw_score = (
        m1
        - m0
        + a * (y - m1) / propensity
        - (1 - a) * (y - m0) / (1.0 - propensity)
    )
    ate = float(aipw_score.mean())
    sampling_se = float(aipw_score.std(ddof=1) / sqrt(n))

    ite = m1 - m0
    ridge_ite = ridge_m1 - ridge_m0
    boosted_ite = boosted_m1 - boosted_m0
    component_estimates = {
        "aipw": ate,
        "outcome_ensemble": float(ite.mean()),
        "ridge_outcome": float(ridge_ite.mean()),
        "boosted_outcome": float(boosted_ite.mean()),
    }
    model_disagreement = float(
        max(abs(value - ate) for value in component_estimates.values())
    )
    z = 1.959963984540054
    interval_half_width = z * sampling_se + model_disagreement
    conservative_equivalent_se = interval_half_width / z

    treated_fraction = float(a.mean())
    att_score = (
        a * (y - m0)
        - (1 - a) * propensity / (1.0 - propensity) * (y - m0)
    ) / treated_fraction
    att = float(att_score.mean())

    treated_weights = a / propensity
    control_weights = (1 - a) / (1.0 - propensity)
    clipped_fraction = float(
        np.mean((raw_propensity < 0.025) | (raw_propensity > 0.975))
    )
    diagnostics = {
        "n": int(n),
        "features": int(x.shape[1]),
        "folds": int(folds),
        "treated_fraction": treated_fraction,
        "raw_propensity_min": float(raw_propensity.min()),
        "raw_propensity_max": float(raw_propensity.max()),
        "clipped_fraction": clipped_fraction,
        "treated_effective_sample_size": _effective_sample_size(treated_weights),
        "control_effective_sample_size": _effective_sample_size(control_weights),
        "ate_sampling_se": sampling_se,
        "ate_model_disagreement": model_disagreement,
        "ate_interval_half_width": interval_half_width,
        "ate_interval_method": (
            "cross-fitted AIPW 95% sampling interval expanded by maximum "
            "cross-fitted outcome-model disagreement"
        ),
        "ate_component_estimates": component_estimates,
        "finite": bool(
            np.isfinite(aipw_score).all()
            and np.isfinite(ite).all()
            and np.isfinite(ridge_ite).all()
            and np.isfinite(boosted_ite).all()
            and np.isfinite(att)
            and np.isfinite(interval_half_width)
        ),
        "positivity_warning": bool(clipped_fraction > 0.10),
    }
    return CausalEstimate(
        ate=ate,
        ate_se=conservative_equivalent_se,
        ate_ci_lower=ate - interval_half_width,
        ate_ci_upper=ate + interval_half_width,
        att=att,
        ite=ite,
        diagnostics=diagnostics,
    )
