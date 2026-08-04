from __future__ import annotations

import argparse
import gc
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
import platform
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA = "fin-abs-004/v4-credit-calibration-benchmark/1"
POLICY_ID = "FIN-ABS-004-PLATT-ENSEMBLE-V1"
DATASET_HANDLE = "sebastiantomczak10/v4-group-corporate-bankruptcy"
DATASET_VERSION = "6"
PRIMARY_FILE = "company_years_h2.parquet"
PRIMARY_SHA256 = "e9fa1b9cb51ea03f3f2582d08674d7b5039e32fb049363f8f2aa12e4dfc76eeb"
UPSTREAM_REPOSITORY = "leokeechye/V4FinBench"
UPSTREAM_COMMIT = "908b88d373a76e0064329e38fc01cba98bebae5f"
TARGET = "main_label"
GROUP = "company"
COUNTRY = "country"
YEAR = "year"
N_SPLITS = 5
RANDOM_STATE = 42
CALIBRATION_SPLIT_SEED = "FIN-ABS-004-CALIBRATION-HALF-V1"
VERIFICATION_SAMPLE_SEED = "FIN-ABS-004-NODE-SAMPLE-V1"
VERIFICATION_SAMPLE_SIZE = 50_000
LATE_YEAR_COUNT = 3
TOP_CAPACITY = 0.005
ABSOLUTE_SCORE_BEFORE = 423
ABSOLUTE_SCORE_PASS_DELTA = 6

COLUMNS_TO_DROP = [
    "company",
    "industry",
    "link",
    "num",
    "emis_id",
    "sector_2",
    "sector_3",
    "sector_4",
    "Revenue/employee",
    "Fixed_assets/employee",
    "EBITDA/cash_flow",
]

XGB_PARAMS = {
    "n_estimators": 200,
    "max_depth": 5,
    "learning_rate": 0.05,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "tree_method": "hist",
    "max_bin": 256,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "random_state": RANDOM_STATE,
    "n_jobs": 2,
    "verbosity": 0,
}

LGB_PARAMS = {
    "n_estimators": 200,
    "max_depth": -1,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "random_state": RANDOM_STATE,
    "n_jobs": 2,
    "verbosity": -1,
    "deterministic": True,
    "force_col_wise": True,
}

WEIGHT_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
EPS = 1e-8


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def runtime_versions() -> dict[str, str | None]:
    def version(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    return {
        "python": platform.python_version(),
        "numpy": version("numpy"),
        "pandas": version("pandas"),
        "pyarrow": version("pyarrow"),
        "scikit_learn": version("scikit-learn"),
        "xgboost": version("xgboost"),
        "lightgbm": version("lightgbm"),
        "kagglehub": version("kagglehub"),
    }


def build_fold_assignments(df) -> np.ndarray:
    rng = np.random.RandomState(RANDOM_STATE)
    mapping: dict[tuple[object, object], int] = {}
    for country, sub in df.groupby(COUNTRY, sort=True):
        companies = sub[GROUP].dropna().unique().copy()
        rng.shuffle(companies)
        for idx, company in enumerate(companies):
            mapping[(country, company)] = idx % N_SPLITS
    folds = np.empty(len(df), dtype=np.int8)
    for pos, row in enumerate(df[[COUNTRY, GROUP]].itertuples(index=False, name=None)):
        folds[pos] = mapping[row]
    return folds


def split_indices(folds: np.ndarray, fold: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    val_fold = fold
    test_fold = (fold + 1) % N_SPLITS
    train = np.where((folds != val_fold) & (folds != test_fold))[0]
    val = np.where(folds == val_fold)[0]
    test = np.where(folds == test_fold)[0]
    return train, val, test


def split_validation_halves(df, val_idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    groups = df.iloc[val_idx][[COUNTRY, GROUP]]
    calibration_mask = np.fromiter(
        (
            int(stable_hash(f"{country}|{company}|{CALIBRATION_SPLIT_SEED}")[-1], 16) % 2 == 0
            for country, company in groups.itertuples(index=False, name=None)
        ),
        dtype=bool,
        count=len(groups),
    )
    calibration = val_idx[calibration_mask]
    selection = val_idx[~calibration_mask]
    return calibration, selection


class Encoder:
    def __init__(self) -> None:
        self.columns: list[str] = []
        self.numeric: set[str] = set()
        self.medians: dict[str, float] = {}
        self.categories: dict[str, dict[str, int]] = {}

    def fit(self, frame) -> "Encoder":
        import pandas as pd

        self.columns = list(frame.columns)
        for column in self.columns:
            series = frame[column]
            if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
                self.numeric.add(column)
                values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
                median = float(values.median()) if values.notna().any() else 0.0
                self.medians[column] = median
            else:
                text = series.astype("string").fillna("__MISSING__")
                unique = sorted(str(value) for value in text.unique())
                self.categories[column] = {value: index for index, value in enumerate(unique)}
        return self

    def transform(self, frame) -> np.ndarray:
        import pandas as pd

        result = np.empty((len(frame), len(self.columns)), dtype=np.float32)
        for index, column in enumerate(self.columns):
            series = frame[column]
            if column in self.numeric:
                values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
                result[:, index] = values.fillna(self.medians[column]).to_numpy(dtype=np.float32)
            else:
                mapping = self.categories[column]
                text = series.astype("string").fillna("__MISSING__")
                result[:, index] = (
                    text.map(mapping).fillna(-1).to_numpy(dtype=np.float32)
                )
        return result


def feature_frame(df):
    drops = [TARGET, *COLUMNS_TO_DROP]
    return df.drop(columns=[column for column in drops if column in df.columns])


def fit_platt(y: np.ndarray, probability: np.ndarray):
    from sklearn.linear_model import LogisticRegression

    clipped = np.clip(probability, EPS, 1 - EPS)
    logit = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    model = LogisticRegression(
        C=1_000_000.0,
        solver="lbfgs",
        max_iter=1000,
        random_state=RANDOM_STATE,
    )
    model.fit(logit, y)
    return model


def apply_platt(model, probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(probability, EPS, 1 - EPS)
    logit = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    return model.predict_proba(logit)[:, 1]


def best_f1_threshold(y: np.ndarray, probability: np.ndarray) -> float:
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(y, probability)
    if len(thresholds) == 0:
        return 0.5
    score = 2 * precision[:-1] * recall[:-1] / np.maximum(
        precision[:-1] + recall[:-1], EPS
    )
    best = int(np.nanargmax(score))
    return float(thresholds[best])


def ece_equal_mass(y: np.ndarray, probability: np.ndarray, bins: int = 20) -> float:
    order = np.argsort(probability, kind="mergesort")
    chunks = np.array_split(order, bins)
    total = len(y)
    error = 0.0
    for chunk in chunks:
        if len(chunk) == 0:
            continue
        error += len(chunk) / total * abs(
            float(probability[chunk].mean()) - float(y[chunk].mean())
        )
    return float(error)


def top_capacity_metrics(
    y: np.ndarray, probability: np.ndarray, capacity: float = TOP_CAPACITY
) -> dict[str, float | int]:
    k = max(1, int(math.ceil(len(y) * capacity)))
    order = np.argpartition(-probability, k - 1)[:k]
    positives = int(y.sum())
    captured = int(y[order].sum())
    return {
        "capacity": capacity,
        "k": k,
        "captured_positives": captured,
        "precision": captured / k,
        "recall": captured / positives if positives else 0.0,
    }


def metrics(
    y: np.ndarray,
    probability: np.ndarray,
    threshold: float,
    prediction: np.ndarray | None = None,
) -> dict[str, Any]:
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        f1_score,
        log_loss,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    p = np.clip(probability, EPS, 1 - EPS)
    pred = (p >= threshold).astype(np.int8) if prediction is None else prediction
    return {
        "rows": int(len(y)),
        "positives": int(y.sum()),
        "positive_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, p)),
        "average_precision": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece_20": ece_equal_mass(y, p, 20),
        "threshold": float(threshold),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "predicted_positive": int(pred.sum()),
        "top_capacity": top_capacity_metrics(y, p),
    }


def select_weight(
    y: np.ndarray, xgb_calibrated: np.ndarray, lgb_calibrated: np.ndarray
) -> tuple[float, dict[str, float]]:
    from sklearn.metrics import brier_score_loss, log_loss

    scores: dict[str, float] = {}
    candidates: list[tuple[float, float, float, float]] = []
    for weight in WEIGHT_GRID:
        probability = weight * xgb_calibrated + (1 - weight) * lgb_calibrated
        brier = float(brier_score_loss(y, probability))
        loss = float(log_loss(y, np.clip(probability, EPS, 1 - EPS), labels=[0, 1]))
        scores[str(weight)] = brier
        candidates.append((brier, loss, abs(weight - 0.5), weight))
    candidates.sort()
    return float(candidates[0][-1]), scores


def company_cluster_ci(
    company: np.ndarray,
    baseline_probability: np.ndarray,
    challenger_probability: np.ndarray,
    y: np.ndarray,
    maximum_companies: int = 20_000,
    repetitions: int = 1000,
) -> dict[str, Any]:
    import pandas as pd

    frame = pd.DataFrame(
        {
            "company": company.astype(str),
            "gain": (baseline_probability - y) ** 2
            - (challenger_probability - y) ** 2,
        }
    )
    means = frame.groupby("company", sort=False)["gain"].mean()
    if len(means) > maximum_companies:
        keep = sorted(
            means.index,
            key=lambda value: stable_hash(f"{value}|CLUSTER-CI-V1"),
        )[:maximum_companies]
        means = means.loc[keep]
    values = means.to_numpy(dtype=np.float64)
    rng = np.random.default_rng(RANDOM_STATE)
    boot = np.empty(repetitions, dtype=np.float64)
    for index in range(repetitions):
        sample = rng.integers(0, len(values), size=len(values))
        boot[index] = values[sample].mean()
    return {
        "companies": int(len(values)),
        "mean_brier_gain": float(values.mean()),
        "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "repetitions": repetitions,
    }


def sample_indices(row_indices: np.ndarray, maximum: int) -> np.ndarray:
    if len(row_indices) <= maximum:
        return np.arange(len(row_indices))
    ordered = sorted(
        range(len(row_indices)),
        key=lambda pos: stable_hash(
            f"{int(row_indices[pos])}|{VERIFICATION_SAMPLE_SEED}"
        ),
    )
    return np.asarray(ordered[:maximum], dtype=np.int64)


def _relative_gain(baseline: float, challenger: float) -> float:
    return (baseline - challenger) / baseline if baseline else 0.0


def run_benchmark(output_dir: Path) -> dict[str, Any]:
    import kagglehub
    import pandas as pd
    import pyarrow.parquet as pq
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier

    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_root = Path(kagglehub.dataset_download(DATASET_HANDLE))
    data_path = dataset_root / PRIMARY_FILE
    actual_hash = sha256_file(data_path)
    if actual_hash != PRIMARY_SHA256:
        raise RuntimeError(
            f"primary parquet hash mismatch: {actual_hash} != {PRIMARY_SHA256}"
        )

    table = pq.read_table(data_path)
    df = table.to_pandas(split_blocks=True, self_destruct=True)
    del table
    gc.collect()

    y_all = df[TARGET].astype(np.int8).to_numpy()
    folds = build_fold_assignments(df)
    features = feature_frame(df)
    years = sorted(int(value) for value in pd.Series(df[YEAR]).dropna().unique())
    late_years = years[-LATE_YEAR_COUNT:]

    row_count = len(df)
    oof_xgb = np.full(row_count, np.nan, dtype=np.float32)
    oof_lgb = np.full(row_count, np.nan, dtype=np.float32)
    oof_challenger = np.full(row_count, np.nan, dtype=np.float32)
    oof_baseline = np.full(row_count, np.nan, dtype=np.float32)
    oof_baseline_pred = np.zeros(row_count, dtype=np.int8)
    oof_challenger_pred = np.zeros(row_count, dtype=np.int8)
    baseline_name = np.empty(row_count, dtype="U8")
    fold_records: list[dict[str, Any]] = []

    for fold in range(N_SPLITS):
        train_idx, val_idx, test_idx = split_indices(folds, fold)
        calibration_idx, selection_idx = split_validation_halves(df, val_idx)

        train_companies = set(df.iloc[train_idx][GROUP].astype(str))
        val_companies = set(df.iloc[val_idx][GROUP].astype(str))
        test_companies = set(df.iloc[test_idx][GROUP].astype(str))
        overlap = {
            "train_val": len(train_companies & val_companies),
            "train_test": len(train_companies & test_companies),
            "val_test": len(val_companies & test_companies),
        }

        encoder = Encoder().fit(features.iloc[train_idx])
        X_train = encoder.transform(features.iloc[train_idx])
        X_cal = encoder.transform(features.iloc[calibration_idx])
        X_sel = encoder.transform(features.iloc[selection_idx])
        X_test = encoder.transform(features.iloc[test_idx])
        y_train = y_all[train_idx]
        y_cal = y_all[calibration_idx]
        y_sel = y_all[selection_idx]
        y_test = y_all[test_idx]

        xgb = XGBClassifier(**XGB_PARAMS)
        xgb.fit(X_train, y_train)
        xgb_cal_raw = xgb.predict_proba(X_cal)[:, 1]
        xgb_sel_raw = xgb.predict_proba(X_sel)[:, 1]
        xgb_test_raw = xgb.predict_proba(X_test)[:, 1]
        del xgb
        gc.collect()

        lgb = LGBMClassifier(**LGB_PARAMS)
        lgb.fit(X_train, y_train)
        lgb_cal_raw = lgb.predict_proba(X_cal)[:, 1]
        lgb_sel_raw = lgb.predict_proba(X_sel)[:, 1]
        lgb_test_raw = lgb.predict_proba(X_test)[:, 1]
        del lgb, X_train, X_cal, X_sel, X_test
        gc.collect()

        xgb_platt = fit_platt(y_cal, xgb_cal_raw)
        lgb_platt = fit_platt(y_cal, lgb_cal_raw)
        xgb_sel_cal = apply_platt(xgb_platt, xgb_sel_raw)
        xgb_test_cal = apply_platt(xgb_platt, xgb_test_raw)
        lgb_sel_cal = apply_platt(lgb_platt, lgb_sel_raw)
        lgb_test_cal = apply_platt(lgb_platt, lgb_test_raw)

        weight, weight_scores = select_weight(y_sel, xgb_sel_cal, lgb_sel_cal)
        challenger_sel = weight * xgb_sel_cal + (1 - weight) * lgb_sel_cal
        challenger_test = weight * xgb_test_cal + (1 - weight) * lgb_test_cal

        xgb_threshold = best_f1_threshold(y_sel, xgb_sel_raw)
        lgb_threshold = best_f1_threshold(y_sel, lgb_sel_raw)
        challenger_threshold = best_f1_threshold(y_sel, challenger_sel)

        xgb_selection = metrics(y_sel, xgb_sel_raw, xgb_threshold)
        lgb_selection = metrics(y_sel, lgb_sel_raw, lgb_threshold)
        chosen = min(
            (
                (-xgb_selection["average_precision"], xgb_selection["brier"], "xgb"),
                (-lgb_selection["average_precision"], lgb_selection["brier"], "lgb"),
            )
        )[-1]
        if chosen == "xgb":
            baseline_test = xgb_test_raw
            baseline_threshold = xgb_threshold
        else:
            baseline_test = lgb_test_raw
            baseline_threshold = lgb_threshold

        xgb_test_metrics = metrics(y_test, xgb_test_raw, xgb_threshold)
        lgb_test_metrics = metrics(y_test, lgb_test_raw, lgb_threshold)
        baseline_test_metrics = metrics(y_test, baseline_test, baseline_threshold)
        challenger_test_metrics = metrics(
            y_test, challenger_test, challenger_threshold
        )

        test_year = pd.to_numeric(df.iloc[test_idx][YEAR], errors="coerce").to_numpy()
        late_mask = np.isin(test_year, late_years)
        late_baseline = metrics(
            y_test[late_mask],
            baseline_test[late_mask],
            baseline_threshold,
        )
        late_challenger = metrics(
            y_test[late_mask],
            challenger_test[late_mask],
            challenger_threshold,
        )

        oof_xgb[test_idx] = xgb_test_raw.astype(np.float32)
        oof_lgb[test_idx] = lgb_test_raw.astype(np.float32)
        oof_challenger[test_idx] = challenger_test.astype(np.float32)
        oof_baseline[test_idx] = baseline_test.astype(np.float32)
        oof_baseline_pred[test_idx] = (
            baseline_test >= baseline_threshold
        ).astype(np.int8)
        oof_challenger_pred[test_idx] = (
            challenger_test >= challenger_threshold
        ).astype(np.int8)
        baseline_name[test_idx] = chosen

        fold_records.append(
            {
                "fold": fold,
                "val_fold": fold,
                "test_fold": (fold + 1) % N_SPLITS,
                "rows": {
                    "train": int(len(train_idx)),
                    "validation": int(len(val_idx)),
                    "calibration": int(len(calibration_idx)),
                    "selection": int(len(selection_idx)),
                    "test": int(len(test_idx)),
                },
                "positives": {
                    "train": int(y_train.sum()),
                    "calibration": int(y_cal.sum()),
                    "selection": int(y_sel.sum()),
                    "test": int(y_test.sum()),
                },
                "company_overlap": overlap,
                "feature_count": int(features.shape[1]),
                "chosen_baseline": chosen,
                "ensemble_xgb_weight": weight,
                "weight_selection_brier": weight_scores,
                "thresholds": {
                    "xgb": xgb_threshold,
                    "lgb": lgb_threshold,
                    "challenger": challenger_threshold,
                    "baseline": baseline_threshold,
                },
                "test_metrics": {
                    "xgb": xgb_test_metrics,
                    "lgb": lgb_test_metrics,
                    "baseline": baseline_test_metrics,
                    "challenger": challenger_test_metrics,
                },
                "late_years": late_years,
                "late_year_metrics": {
                    "baseline": late_baseline,
                    "challenger": late_challenger,
                },
            }
        )

        del (
            encoder,
            xgb_cal_raw,
            xgb_sel_raw,
            xgb_test_raw,
            lgb_cal_raw,
            lgb_sel_raw,
            lgb_test_raw,
            xgb_sel_cal,
            xgb_test_cal,
            lgb_sel_cal,
            lgb_test_cal,
            challenger_sel,
            challenger_test,
            baseline_test,
        )
        gc.collect()

    if np.isnan(oof_challenger).any() or np.isnan(oof_baseline).any():
        raise RuntimeError("OOF predictions are incomplete")

    overall_baseline = metrics(
        y_all, oof_baseline, 0.5, prediction=oof_baseline_pred
    )
    overall_challenger = metrics(
        y_all, oof_challenger, 0.5, prediction=oof_challenger_pred
    )
    overall_xgb = metrics(y_all, oof_xgb, 0.5)
    overall_lgb = metrics(y_all, oof_lgb, 0.5)

    year_values = pd.to_numeric(df[YEAR], errors="coerce").to_numpy()
    late_mask_all = np.isin(year_values, late_years)
    late_overall = {
        "baseline": metrics(
            y_all[late_mask_all],
            oof_baseline[late_mask_all],
            0.5,
            prediction=oof_baseline_pred[late_mask_all],
        ),
        "challenger": metrics(
            y_all[late_mask_all],
            oof_challenger[late_mask_all],
            0.5,
            prediction=oof_challenger_pred[late_mask_all],
        ),
    }

    country_metrics: dict[str, Any] = {}
    for country in sorted(str(value) for value in pd.Series(df[COUNTRY]).unique()):
        mask = df[COUNTRY].astype(str).to_numpy() == country
        country_metrics[country] = {
            "baseline": metrics(
                y_all[mask],
                oof_baseline[mask],
                0.5,
                prediction=oof_baseline_pred[mask],
            ),
            "challenger": metrics(
                y_all[mask],
                oof_challenger[mask],
                0.5,
                prediction=oof_challenger_pred[mask],
            ),
        }

    cluster_ci = company_cluster_ci(
        df[GROUP].astype(str).to_numpy(),
        oof_baseline.astype(np.float64),
        oof_challenger.astype(np.float64),
        y_all.astype(np.float64),
    )

    permutation = np.roll(oof_challenger, 1)
    permutation_metrics = metrics(y_all, permutation, 0.5)

    brier_wins = sum(
        record["test_metrics"]["challenger"]["brier"]
        < record["test_metrics"]["baseline"]["brier"]
        for record in fold_records
    )
    ece_wins = sum(
        record["test_metrics"]["challenger"]["ece_20"]
        < record["test_metrics"]["baseline"]["ece_20"]
        for record in fold_records
    )
    country_brier_wins = sum(
        value["challenger"]["brier"] < value["baseline"]["brier"]
        for value in country_metrics.values()
    )
    maximum_country_brier_loss = max(
        value["challenger"]["brier"] - value["baseline"]["brier"]
        for value in country_metrics.values()
    )

    brier_relative_gain = _relative_gain(
        overall_baseline["brier"], overall_challenger["brier"]
    )
    logloss_relative_gain = _relative_gain(
        overall_baseline["log_loss"], overall_challenger["log_loss"]
    )
    ece_relative_gain = _relative_gain(
        overall_baseline["ece_20"], overall_challenger["ece_20"]
    )

    gate_checks = {
        "dataset_version_frozen": DATASET_VERSION == "6",
        "primary_hash_exact": actual_hash == PRIMARY_SHA256,
        "five_folds_complete": len(fold_records) == N_SPLITS,
        "zero_company_overlap": all(
            all(value == 0 for value in record["company_overlap"].values())
            for record in fold_records
        ),
        "minimum_test_positives_400": min(
            record["positives"]["test"] for record in fold_records
        )
        >= 400,
        "baseline_roc_auc_at_least_075": overall_baseline["roc_auc"] >= 0.75,
        "baseline_average_precision_at_least_003": overall_baseline[
            "average_precision"
        ]
        >= 0.03,
        "challenger_brier_relative_gain_2pct": brier_relative_gain >= 0.02,
        "challenger_logloss_relative_gain_1pct": logloss_relative_gain >= 0.01,
        "challenger_ece_relative_gain_10pct": ece_relative_gain >= 0.10,
        "challenger_roc_noninferior": overall_challenger["roc_auc"]
        >= overall_baseline["roc_auc"] - 0.001,
        "challenger_ap_noninferior": overall_challenger["average_precision"]
        >= overall_baseline["average_precision"] - 0.001,
        "challenger_f1_noninferior": overall_challenger["f1"]
        >= overall_baseline["f1"] - 0.005,
        "challenger_top_precision_noninferior": overall_challenger["top_capacity"][
            "precision"
        ]
        >= overall_baseline["top_capacity"]["precision"] - 0.005,
        "challenger_top_recall_noninferior": overall_challenger["top_capacity"][
            "recall"
        ]
        >= overall_baseline["top_capacity"]["recall"] - 0.005,
        "brier_wins_four_folds": brier_wins >= 4,
        "ece_wins_four_folds": ece_wins >= 4,
        "late_year_brier_better": late_overall["challenger"]["brier"]
        < late_overall["baseline"]["brier"],
        "late_year_ap_noninferior": late_overall["challenger"]["average_precision"]
        >= late_overall["baseline"]["average_precision"] - 0.002,
        "cluster_ci_lower_positive": cluster_ci["ci95"][0] > 0.0,
        "country_brier_wins_three": country_brier_wins >= 3,
        "no_material_country_brier_harm": maximum_country_brier_loss <= 0.0005,
        "permutation_degrades_ap": permutation_metrics["average_precision"]
        < overall_challenger["average_precision"],
        "permutation_worsens_brier": permutation_metrics["brier"]
        > overall_challenger["brier"],
    }
    passed = all(gate_checks.values())
    score_after = (
        ABSOLUTE_SCORE_BEFORE + ABSOLUTE_SCORE_PASS_DELTA
        if passed
        else ABSOLUTE_SCORE_BEFORE
    )

    oof = pd.DataFrame(
        {
            "row_index": np.arange(row_count, dtype=np.int64),
            "fold": folds,
            "country": df[COUNTRY].astype(str).to_numpy(),
            "company": df[GROUP].astype(str).to_numpy(),
            "year": year_values,
            "y": y_all,
            "xgb_probability": oof_xgb,
            "lgb_probability": oof_lgb,
            "baseline_name": baseline_name,
            "baseline_probability": oof_baseline,
            "challenger_probability": oof_challenger,
            "baseline_prediction": oof_baseline_pred,
            "challenger_prediction": oof_challenger_pred,
        }
    )
    predictions_path = output_dir / "oof_predictions.parquet"
    oof.to_parquet(predictions_path, index=False, compression="zstd")

    verify_positions = sample_indices(oof["row_index"].to_numpy(), VERIFICATION_SAMPLE_SIZE)
    verification_sample = oof.iloc[verify_positions][
        [
            "row_index",
            "fold",
            "country",
            "year",
            "y",
            "baseline_probability",
            "challenger_probability",
            "baseline_prediction",
            "challenger_prediction",
        ]
    ]
    sample_path = output_dir / "verification_sample.jsonl.gz"
    with gzip.open(sample_path, "wt", encoding="utf-8") as handle:
        for row in verification_sample.to_dict(orient="records"):
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    sample_baseline = metrics(
        verification_sample["y"].to_numpy(dtype=np.int8),
        verification_sample["baseline_probability"].to_numpy(dtype=np.float64),
        0.5,
        prediction=verification_sample["baseline_prediction"].to_numpy(dtype=np.int8),
    )
    sample_challenger = metrics(
        verification_sample["y"].to_numpy(dtype=np.int8),
        verification_sample["challenger_probability"].to_numpy(dtype=np.float64),
        0.5,
        prediction=verification_sample["challenger_prediction"].to_numpy(dtype=np.int8),
    )

    payload = {
        "schema": SCHEMA,
        "policy_id": POLICY_ID,
        "status": "PASS_CREDIT_CALIBRATION" if passed else "FALSIFIED_CREDIT_CALIBRATION",
        "data": {
            "dataset_handle": DATASET_HANDLE,
            "dataset_version": DATASET_VERSION,
            "primary_file": PRIMARY_FILE,
            "primary_sha256": actual_hash,
            "rows": row_count,
            "features": int(features.shape[1]),
            "positive_labels": int(y_all.sum()),
            "years": years,
            "late_years": late_years,
        },
        "protocol": {
            "upstream_repository": UPSTREAM_REPOSITORY,
            "upstream_commit": UPSTREAM_COMMIT,
            "folds": N_SPLITS,
            "random_state": RANDOM_STATE,
            "group_column": GROUP,
            "country_column": COUNTRY,
            "validation_halves": CALIBRATION_SPLIT_SEED,
            "models": {
                "xgboost": XGB_PARAMS,
                "lightgbm": LGB_PARAMS,
                "challenger": (
                    "Platt-calibrate both fixed tree models on the calibration half; "
                    "select a convex weight from a frozen five-point grid on the "
                    "selection half; no test labels influence calibration, weighting, "
                    "thresholds, or baseline choice."
                ),
            },
            "top_capacity": TOP_CAPACITY,
            "score_delta_if_all_gates_pass": ABSOLUTE_SCORE_PASS_DELTA,
            "score_dimensions": {
                "external_validation": 4,
                "cross_domain_generality": 2,
                "world_sota": 0,
                "historical_originality": 0,
            },
        },
        "folds": fold_records,
        "overall": {
            "xgb": overall_xgb,
            "lightgbm": overall_lgb,
            "baseline": overall_baseline,
            "challenger": overall_challenger,
            "brier_relative_gain": brier_relative_gain,
            "logloss_relative_gain": logloss_relative_gain,
            "ece_relative_gain": ece_relative_gain,
            "brier_fold_wins": brier_wins,
            "ece_fold_wins": ece_wins,
        },
        "late_year": late_overall,
        "country_metrics": country_metrics,
        "cluster_brier_gain": cluster_ci,
        "permutation_control": permutation_metrics,
        "gate_checks": gate_checks,
        "verification_sample": {
            "rows": int(len(verification_sample)),
            "seed": VERIFICATION_SAMPLE_SEED,
            "sample_sha256": sha256_file(sample_path),
            "baseline_metrics": sample_baseline,
            "challenger_metrics": sample_challenger,
        },
        "artifacts": {
            "oof_predictions_sha256": sha256_file(predictions_path),
            "verification_sample_sha256": sha256_file(sample_path),
        },
        "runtime": runtime_versions(),
        "absolute_score": {
            "before": ABSOLUTE_SCORE_BEFORE,
            "after": score_after,
            "delta": score_after - ABSOLUTE_SCORE_BEFORE,
            "boundary": (
                "A complete pass earns six points only for external validation "
                "and cross-domain generality. It earns no SOTA or originality points."
            ),
        },
        "boundary": (
            "The claim is limited to calibration and selective reliability for the "
            "V4FinBench one-year-ahead composite distress label. It is not a causal "
            "bankruptcy mechanism, a lending decision, or universal credit SOTA."
        ),
    }
    report = {"payload": payload, "sha256": digest(payload)}
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(
        "\n".join(
            [
                "# FIN-ABS-004 — sealed credit calibration benchmark",
                "",
                f"- Status: **{payload['status']}**",
                f"- Rows / positives: **{row_count:,} / {int(y_all.sum()):,}**",
                f"- Baseline AP / Brier: **{overall_baseline['average_precision']:.6f} / {overall_baseline['brier']:.8f}**",
                f"- Challenger AP / Brier: **{overall_challenger['average_precision']:.6f} / {overall_challenger['brier']:.8f}**",
                f"- Brier relative gain: **{brier_relative_gain:.2%}**",
                f"- Log-loss relative gain: **{logloss_relative_gain:.2%}**",
                f"- ECE relative gain: **{ece_relative_gain:.2%}**",
                f"- Brier fold wins: **{brier_wins}/5**",
                f"- ECE fold wins: **{ece_wins}/5**",
                f"- Cluster CI: **[{cluster_ci['ci95'][0]:.8f}, {cluster_ci['ci95'][1]:.8f}]**",
                f"- Absolute score: **{ABSOLUTE_SCORE_BEFORE} → {score_after}**",
                f"- Report SHA-256: `{report['sha256']}`",
                "",
                payload["boundary"],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "baseline_ap": overall_baseline["average_precision"],
                "challenger_ap": overall_challenger["average_precision"],
                "baseline_brier": overall_baseline["brier"],
                "challenger_brier": overall_challenger["brier"],
                "brier_gain": brier_relative_gain,
                "score_before": ABSOLUTE_SCORE_BEFORE,
                "score_after": score_after,
                "report_sha256": report["sha256"],
            },
            sort_keys=True,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_benchmark(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
