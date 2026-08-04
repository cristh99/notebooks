from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import rankdata, skew
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors


@dataclass(frozen=True)
class AnomalyResult:
    scores: np.ndarray
    diagnostics: dict[str, Any]


def _as_finite_matrix(X: np.ndarray) -> np.ndarray:
    values = np.asarray(X, dtype=float)
    if values.ndim != 2:
        raise ValueError("X must be a two-dimensional array")
    if values.shape[0] < 20:
        raise ValueError("at least 20 rows are required")
    if values.shape[1] < 1:
        raise ValueError("at least one feature is required")
    values = values.copy()
    values[~np.isfinite(values)] = np.nan
    medians = np.nanmedian(values, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    missing = np.isnan(values)
    if missing.any():
        values[missing] = np.take(medians, np.where(missing)[1])
    q25, q75 = np.quantile(values, [0.25, 0.75], axis=0)
    iqr = q75 - q25
    mad = np.median(np.abs(values - medians), axis=0) * 1.4826
    std = np.std(values, axis=0)
    scale = np.where(iqr > 1e-10, iqr, np.where(mad > 1e-10, mad, np.where(std > 1e-10, std, 1.0)))
    keep = np.isfinite(scale) & (scale > 1e-12)
    if not keep.any():
        return np.zeros((values.shape[0], 1), dtype=float)
    values = (values[:, keep] - medians[keep]) / scale[keep]
    return np.clip(values, -20.0, 20.0).astype(float, copy=False)


def _unit_rank(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    finite = np.isfinite(array)
    replacement = float(np.median(array[finite])) if finite.any() else 0.0
    array = np.nan_to_num(array, nan=replacement, posinf=replacement, neginf=replacement)
    if array.size <= 1:
        return np.zeros_like(array)
    return (rankdata(array, method="average") - 1.0) / (array.size - 1.0)


def _distance_representation(Z: np.ndarray, random_state: int) -> tuple[np.ndarray, dict[str, Any]]:
    n, d = Z.shape
    if d <= 24:
        return Z, {"distance_representation": "robust_scaled", "distance_features": int(d)}
    pca = PCA(n_components=min(32, d, n - 1), whiten=True, random_state=random_state)
    projected = pca.fit_transform(Z)
    return projected, {"distance_representation": "whitened_pca", "distance_features": int(projected.shape[1]), "pca_explained_variance": float(np.sum(pca.explained_variance_ratio_))}


def _knn_streams(Z: np.ndarray) -> dict[str, np.ndarray]:
    n = Z.shape[0]
    k_values = sorted({min(max(5, int(round(np.sqrt(n) / 3))), n - 1), min(15, n - 1), min(35, n - 1)})
    model = NearestNeighbors(n_neighbors=max(k_values) + 1, metric="euclidean", n_jobs=-1)
    distances = model.fit(Z).kneighbors(return_distance=True)[0][:, 1:]
    return {f"knn_{k}": 0.65 * distances[:, k - 1] + 0.35 * np.mean(distances[:, :k], axis=1) for k in k_values}


def _lof_stream(Z: np.ndarray) -> np.ndarray:
    n = Z.shape[0]
    k = min(max(10, int(round(np.sqrt(n)))), 50, n - 1)
    model = LocalOutlierFactor(n_neighbors=k, contamination="auto", novelty=False, n_jobs=-1)
    model.fit_predict(Z)
    return -np.asarray(model.negative_outlier_factor_, dtype=float)


def _iforest_score(Z: np.ndarray, random_state: int, n_estimators: int = 192) -> np.ndarray:
    model = IsolationForest(n_estimators=n_estimators, max_samples=min(1024, len(Z)), max_features=1.0, contamination="auto", bootstrap=False, random_state=random_state, n_jobs=-1)
    model.fit(Z)
    return -model.score_samples(Z)


def _isolation_streams(Z: np.ndarray, random_state: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(random_state)
    d = Z.shape[1]
    streams = {"iforest": _iforest_score(Z, random_state)}
    if d > 1:
        q, _ = np.linalg.qr(rng.normal(size=(d, d)))
        streams["rotated_iforest"] = _iforest_score(Z @ q, random_state + 17, 160)
    hidden = min(64, max(16, 2 * d))
    weights = rng.normal(size=(d, hidden)) / max(np.sqrt(d), 1.0)
    representation = np.tanh(Z @ weights + rng.uniform(-1.0, 1.0, size=hidden))
    streams["random_representation_iforest"] = _iforest_score(representation, random_state + 31, 160)
    return streams


def _pca_residual(Z: np.ndarray, random_state: int) -> np.ndarray:
    n, d = Z.shape
    if d <= 2:
        return np.linalg.norm(Z, axis=1)
    pca = PCA(n_components=min(max(1, d // 2), 20, n - 1, d - 1), random_state=random_state)
    reconstruction = pca.inverse_transform(pca.fit_transform(Z))
    return np.mean((Z - reconstruction) ** 2, axis=1)


def _hbos_score(Z: np.ndarray) -> np.ndarray:
    n, d = Z.shape
    values = Z[:, np.argsort(np.var(Z, axis=0))[-64:]] if d > 64 else Z
    bins = min(32, max(8, int(round(np.sqrt(n)))))
    feature_scores: list[np.ndarray] = []
    for column in values.T:
        edges = np.unique(np.quantile(column, np.linspace(0.0, 1.0, bins + 1)))
        if edges.size < 3:
            continue
        counts, edges = np.histogram(column, bins=edges)
        probabilities = (counts + 1.0) / (counts.sum() + counts.size)
        indices = np.clip(np.searchsorted(edges, column, side="right") - 1, 0, probabilities.size - 1)
        feature_scores.append(-np.log(probabilities[indices] + 1e-12))
    if not feature_scores:
        return np.linalg.norm(values, axis=1)
    matrix = np.column_stack(feature_scores)
    top = min(matrix.shape[1], max(1, int(round(np.sqrt(matrix.shape[1])))))
    return np.mean(np.partition(matrix, -top, axis=1)[:, -top:], axis=1)


def score_anomalies(X: np.ndarray, *, random_state: int = 1729) -> AnomalyResult:
    Z = _as_finite_matrix(X)
    Z_distance, representation_diag = _distance_representation(Z, random_state)
    raw_streams: dict[str, np.ndarray] = {}
    raw_streams.update(_knn_streams(Z_distance))
    raw_streams["lof"] = _lof_stream(Z_distance)
    raw_streams.update(_isolation_streams(Z_distance, random_state))
    raw_streams["pca_residual"] = _pca_residual(Z, random_state)
    raw_streams["hbos"] = _hbos_score(Z)
    ranked = {name: _unit_rank(score) for name, score in raw_streams.items()}
    names = list(ranked)
    rank_matrix = np.column_stack([ranked[name] for name in names])
    with np.errstate(invalid="ignore", divide="ignore"):
        correlations = np.corrcoef(rank_matrix, rowvar=False)
    correlations = np.nan_to_num(correlations, nan=0.0, posinf=0.0, neginf=0.0)
    centrality = (np.clip(correlations, 0.0, 1.0).sum(axis=1) - 1.0) / max(len(names) - 1, 1)
    all_weights = (0.5 + centrality) / np.sum(0.5 + centrality)
    local_reference = next(raw_streams[name] for name in names if name.startswith("knn_"))
    median_local = float(np.median(local_reference))
    local_dispersion = float((np.quantile(local_reference, 0.75) - np.quantile(local_reference, 0.25)) / max(abs(median_local), 1e-12))
    radial_skew = float(np.nan_to_num(skew(np.linalg.norm(Z_distance, axis=1), bias=False), nan=0.0))
    local_weight = float(np.clip(0.5 + 0.15 * np.tanh(np.log1p(max(local_dispersion, 0.0)) - 0.35 * max(radial_skew, 0.0)), 0.35, 0.65))
    ordered = np.sort(rank_matrix, axis=1)
    top_count = min(3, ordered.shape[1])
    final = 0.70 * np.mean(ordered[:, -top_count:], axis=1) + 0.30 * ordered[:, -min(2, ordered.shape[1])]
    final = _unit_rank(final)
    diagnostics: dict[str, Any] = {"rows": int(Z.shape[0]), "features_after_cleaning": int(Z.shape[1]), "stream_names": names, "stream_weights": {name: float(all_weights[i]) for i, name in enumerate(names)}, "local_weight": local_weight, "global_weight": 1.0 - local_weight, "local_dispersion": local_dispersion, "radial_skew": radial_skew, "finite": bool(np.isfinite(final).all()), **representation_diag}
    return AnomalyResult(scores=final, diagnostics=diagnostics)
