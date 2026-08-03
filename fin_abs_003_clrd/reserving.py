from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .audit import CUTOFFS, TARGET_YEAR, build_cases, normalized_frame

BASELINE_METHODS = (
    "COMPANY_CHAIN_LADDER",
    "LOB_POOLED_CHAIN_LADDER",
    "BORN_HUETTER_FERGUSON",
    "CAPE_COD",
)
CHALLENGER_WEIGHTS = {
    "ROBUST_CRED_25": 0.25,
    "ROBUST_CRED_50": 0.50,
    "ROBUST_CRED_75": 0.75,
}
BOOTSTRAP_REPLICATES = 5000
BOOTSTRAP_SEED = 20260803


@dataclass(frozen=True)
class FactorSet:
    pooled: dict[tuple[str, int], float]
    robust_pooled: dict[tuple[str, int], float]
    credibility_volume: dict[tuple[str, int], float]
    company: dict[tuple[str, str, int], float]
    company_volume: dict[tuple[str, str, int], float]
    target_elr: dict[str, float]
    cape_cod_elr: dict[tuple[str, int], float]


def finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return np.isfinite(number) and number > 0


def link_rows(frame: pd.DataFrame, cutoff: int) -> pd.DataFrame:
    visible = frame.loc[frame["DevelopmentYear"] <= cutoff].copy()
    columns = [
        "GRCODE",
        "LOB",
        "AccidentYear",
        "DevelopmentLag",
        "CumPaidLoss",
        "split",
    ]
    current = visible[columns].rename(
        columns={
            "DevelopmentLag": "lag",
            "CumPaidLoss": "current_paid",
        }
    )
    following = visible[columns].rename(
        columns={
            "DevelopmentLag": "next_lag",
            "CumPaidLoss": "next_paid",
            "split": "next_split",
        }
    )
    current["next_lag"] = current["lag"] + 1
    merged = current.merge(
        following,
        on=["GRCODE", "LOB", "AccidentYear", "next_lag"],
        how="inner",
        validate="one_to_one",
    )
    valid = (
        merged["current_paid"].map(finite_positive)
        & merged["next_paid"].map(finite_positive)
        & (merged["split"] == merged["next_split"])
    )
    output = merged.loc[valid].copy()
    output["ratio"] = output["next_paid"] / output["current_paid"]
    return output


def weighted_factor(group: pd.DataFrame) -> tuple[float, float]:
    denominator = float(group["current_paid"].sum())
    numerator = float(group["next_paid"].sum())
    if denominator <= 0 or not np.isfinite(denominator + numerator):
        return 1.0, 0.0
    return max(numerator / denominator, 1e-8), denominator


def company_factor_table(links: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (grcode, lob, lag), group in links.groupby(
        ["GRCODE", "LOB", "lag"], sort=True
    ):
        factor, volume = weighted_factor(group)
        rows.append(
            {
                "GRCODE": str(grcode),
                "LOB": str(lob),
                "lag": int(lag),
                "factor": factor,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


def training_factor_maps(
    links: pd.DataFrame,
) -> tuple[
    dict[tuple[str, int], float],
    dict[tuple[str, int], float],
    dict[tuple[str, int], float],
]:
    train = links.loc[links["split"] == "train"].copy()
    pooled: dict[tuple[str, int], float] = {}
    robust: dict[tuple[str, int], float] = {}
    credibility_volume: dict[tuple[str, int], float] = {}
    company = company_factor_table(train)
    for (lob, lag), group in train.groupby(["LOB", "lag"], sort=True):
        key = (str(lob), int(lag))
        pooled[key], _ = weighted_factor(group)
        company_group = company.loc[
            (company["LOB"] == str(lob)) & (company["lag"] == int(lag))
        ].copy()
        values = company_group["factor"].to_numpy(dtype=float)
        weights = company_group["volume"].to_numpy(dtype=float)
        if len(values) == 0:
            robust[key] = pooled[key]
            credibility_volume[key] = 0.0
            continue
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        if mad > 1e-12:
            scale = 1.4826 * mad
            values = np.clip(values, max(1e-8, median - 3.0 * scale), median + 3.0 * scale)
        if float(weights.sum()) <= 0:
            robust[key] = float(np.mean(values))
        else:
            robust[key] = float(np.average(values, weights=weights))
        credibility_volume[key] = float(np.median(weights)) if len(weights) else 0.0
    return pooled, robust, credibility_volume


def target_elr_by_lob(frame: pd.DataFrame) -> dict[str, float]:
    target = frame.loc[
        (frame["DevelopmentYear"] == TARGET_YEAR)
        & (frame["split"] == "train")
        & frame["CumPaidLoss"].map(finite_positive)
        & frame["EarnedPremNet"].map(finite_positive)
    ].copy()
    output: dict[str, float] = {}
    for lob, group in target.groupby("LOB", sort=True):
        denominator = float(group["EarnedPremNet"].sum())
        output[str(lob)] = (
            float(group["CumPaidLoss"].sum()) / denominator
            if denominator > 0
            else 0.0
        )
    return output


def factor_product(
    factors: Mapping[tuple[str, int], float],
    lob: str,
    current_lag: int,
    target_lag: int,
) -> float:
    value = 1.0
    for lag in range(int(current_lag), int(target_lag)):
        value *= max(float(factors.get((lob, lag), 1.0)), 1e-8)
    return value


def cape_cod_elr_by_lob_cutoff(
    cases: pd.DataFrame,
    pooled: Mapping[tuple[str, int], float],
) -> dict[tuple[str, int], float]:
    output: dict[tuple[str, int], float] = {}
    train = cases.loc[cases["split"] == "train"].copy()
    for (lob, cutoff), group in train.groupby(["LOB", "cutoff"], sort=True):
        numerator = 0.0
        denominator = 0.0
        for row in group.itertuples(index=False):
            product = factor_product(
                pooled,
                str(lob),
                int(row.current_development_lag),
                int(row.target_development_lag),
            )
            percent = min(max(1.0 / max(product, 1e-8), 0.0), 1.0)
            numerator += float(row.current_paid)
            denominator += float(row.earned_premium_net) * percent
        output[(str(lob), int(cutoff))] = (
            numerator / denominator if denominator > 0 else 0.0
        )
    return output


def build_factor_set(frame: pd.DataFrame, cases: pd.DataFrame, cutoff: int) -> FactorSet:
    links = link_rows(frame, cutoff)
    company_table = company_factor_table(links)
    pooled, robust, credibility_volume = training_factor_maps(links)
    company = {
        (str(row.GRCODE), str(row.LOB), int(row.lag)): float(row.factor)
        for row in company_table.itertuples(index=False)
    }
    company_volume = {
        (str(row.GRCODE), str(row.LOB), int(row.lag)): float(row.volume)
        for row in company_table.itertuples(index=False)
    }
    target_elr = target_elr_by_lob(frame)
    cape_cod = cape_cod_elr_by_lob_cutoff(
        cases.loc[cases["cutoff"] == cutoff], pooled
    )
    return FactorSet(
        pooled=pooled,
        robust_pooled=robust,
        credibility_volume=credibility_volume,
        company=company,
        company_volume=company_volume,
        target_elr=target_elr,
        cape_cod_elr=cape_cod,
    )


def company_product(row: Any, factors: FactorSet) -> float:
    value = 1.0
    for lag in range(
        int(row.current_development_lag), int(row.target_development_lag)
    ):
        key = (str(row.GRCODE), str(row.LOB), lag)
        factor = factors.company.get(
            key, factors.pooled.get((str(row.LOB), lag), 1.0)
        )
        value *= max(float(factor), 1e-8)
    return value


def robust_credibility_product(row: Any, factors: FactorSet) -> float:
    value = 1.0
    for lag in range(
        int(row.current_development_lag), int(row.target_development_lag)
    ):
        company_key = (str(row.GRCODE), str(row.LOB), lag)
        pooled_key = (str(row.LOB), lag)
        pooled_factor = float(factors.robust_pooled.get(pooled_key, 1.0))
        company_factor = float(factors.company.get(company_key, pooled_factor))
        volume = float(factors.company_volume.get(company_key, 0.0))
        reference = float(factors.credibility_volume.get(pooled_key, 0.0))
        credibility = volume / (volume + reference) if volume + reference > 0 else 0.0
        factor = credibility * company_factor + (1.0 - credibility) * pooled_factor
        value *= max(factor, 1e-8)
    return value


def reserve_from_target(current: float, target: float) -> float:
    return max(float(target) - float(current), 0.0)


def predict_cases(frame: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    factor_sets = {
        cutoff: build_factor_set(frame, cases, cutoff) for cutoff in CUTOFFS
    }
    for row in cases.itertuples(index=False):
        factors = factor_sets[int(row.cutoff)]
        current = float(row.current_paid)
        premium = float(row.earned_premium_net)
        lob = str(row.LOB)
        pooled_product = factor_product(
            factors.pooled,
            lob,
            int(row.current_development_lag),
            int(row.target_development_lag),
        )
        company_target = current * company_product(row, factors)
        pooled_target = current * pooled_product
        percent = min(max(1.0 / max(pooled_product, 1e-8), 0.0), 1.0)
        bf_expected_target = premium * float(factors.target_elr.get(lob, 0.0))
        bf_target = current + bf_expected_target * (1.0 - percent)
        cape_expected_target = premium * float(
            factors.cape_cod_elr.get((lob, int(row.cutoff)), 0.0)
        )
        cape_target = current + cape_expected_target * (1.0 - percent)
        robust_target = current * robust_credibility_product(row, factors)
        predictions = {
            "COMPANY_CHAIN_LADDER": reserve_from_target(current, company_target),
            "LOB_POOLED_CHAIN_LADDER": reserve_from_target(current, pooled_target),
            "BORN_HUETTER_FERGUSON": reserve_from_target(current, bf_target),
            "CAPE_COD": reserve_from_target(current, cape_target),
        }
        bf_reserve = predictions["BORN_HUETTER_FERGUSON"]
        robust_reserve = reserve_from_target(current, robust_target)
        for name, weight in CHALLENGER_WEIGHTS.items():
            predictions[name] = weight * robust_reserve + (1.0 - weight) * bf_reserve
        base = row._asdict()
        for method, prediction in predictions.items():
            output.append(
                {
                    **base,
                    "method": method,
                    "prediction": max(float(prediction), 0.0),
                }
            )
    return pd.DataFrame(output)


def method_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    actual = frame["actual_reserve"].to_numpy(dtype=float)
    predicted = frame["prediction"].to_numpy(dtype=float)
    errors = predicted - actual
    denominator = float(np.sum(actual))
    wape = float(np.sum(np.abs(errors)) / denominator) if denominator > 0 else None
    calibration = float(np.sum(predicted) / denominator) if denominator > 0 else None
    positive = actual > 0
    ape = np.abs(errors[positive]) / actual[positive] if positive.any() else np.array([])
    lob_wape: dict[str, float | None] = {}
    for lob, group in frame.groupby("LOB", sort=True):
        lob_actual = group["actual_reserve"].to_numpy(dtype=float)
        lob_error = (
            group["prediction"].to_numpy(dtype=float) - lob_actual
        )
        lob_denominator = float(np.sum(lob_actual))
        lob_wape[str(lob)] = (
            float(np.sum(np.abs(lob_error)) / lob_denominator)
            if lob_denominator > 0
            else None
        )
    cutoff_wape: dict[str, float | None] = {}
    for cutoff, group in frame.groupby("cutoff", sort=True):
        cutoff_actual = group["actual_reserve"].to_numpy(dtype=float)
        cutoff_error = (
            group["prediction"].to_numpy(dtype=float) - cutoff_actual
        )
        cutoff_denominator = float(np.sum(cutoff_actual))
        cutoff_wape[str(int(cutoff))] = (
            float(np.sum(np.abs(cutoff_error)) / cutoff_denominator)
            if cutoff_denominator > 0
            else None
        )
    return {
        "cases": int(len(frame)),
        "actual_total": denominator,
        "predicted_total": float(np.sum(predicted)),
        "wape": wape,
        "calibration_ratio": calibration,
        "calibration_error": abs(calibration - 1.0) if calibration is not None else None,
        "median_ape": float(np.median(ape)) if len(ape) else None,
        "p95_ape": float(np.quantile(ape, 0.95)) if len(ape) else None,
        "under_reserving_frequency": float(np.mean(predicted < actual)),
        "aggregate_under_reserve": float(np.sum(np.maximum(actual - predicted, 0.0))),
        "lob_wape": lob_wape,
        "cutoff_wape": cutoff_wape,
    }


def all_metrics(predictions: pd.DataFrame, split: str) -> dict[str, dict[str, Any]]:
    subset = predictions.loc[predictions["split"] == split]
    return {
        str(method): method_metrics(group)
        for method, group in subset.groupby("method", sort=True)
    }


def selection_key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, float, str]:
    name, metrics = item
    return (
        float(metrics["wape"] if metrics["wape"] is not None else np.inf),
        float(
            metrics["calibration_error"]
            if metrics["calibration_error"] is not None
            else np.inf
        ),
        float(metrics["p95_ape"] if metrics["p95_ape"] is not None else np.inf),
        name,
    )


def select_method(
    metrics: Mapping[str, dict[str, Any]], methods: Sequence[str]
) -> str:
    candidates = [(name, metrics[name]) for name in methods]
    return min(candidates, key=selection_key)[0]


def lcg_indices(seed: int, count: int, modulus: int) -> list[int]:
    state = seed & 0xFFFFFFFF
    output: list[int] = []
    for _ in range(count):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        output.append(state % modulus)
    return output


def paired_entity_bootstrap(
    test_predictions: pd.DataFrame,
    baseline: str,
    challenger: str,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    selected = test_predictions.loc[
        test_predictions["method"].isin([baseline, challenger])
    ].copy()
    pivot = selected.pivot_table(
        index=["GRCODE", "case_id"],
        columns="method",
        values=["actual_reserve", "prediction"],
        aggfunc="first",
    )
    entities = sorted(set(pivot.index.get_level_values("GRCODE")))
    entity_values: dict[str, tuple[float, float]] = {}
    for entity in entities:
        group = pivot.xs(entity, level="GRCODE")
        actual = group[("actual_reserve", baseline)].to_numpy(dtype=float)
        baseline_prediction = group[("prediction", baseline)].to_numpy(dtype=float)
        challenger_prediction = group[("prediction", challenger)].to_numpy(dtype=float)
        denominator = float(np.sum(actual))
        if denominator <= 0:
            continue
        baseline_wape = float(np.sum(np.abs(baseline_prediction - actual)) / denominator)
        challenger_wape = float(np.sum(np.abs(challenger_prediction - actual)) / denominator)
        entity_values[entity] = (baseline_wape, challenger_wape)
    entities = sorted(entity_values)
    improvements = np.array(
        [entity_values[entity][0] - entity_values[entity][1] for entity in entities],
        dtype=float,
    )
    if len(improvements) == 0:
        return {
            "entities": 0,
            "mean_improvement": None,
            "lower_95": None,
            "upper_95": None,
            "replicates": 0,
            "seed": BOOTSTRAP_SEED,
        }
    indices = lcg_indices(
        BOOTSTRAP_SEED,
        replicates * len(improvements),
        len(improvements),
    )
    means: list[float] = []
    cursor = 0
    for _ in range(replicates):
        sample = [
            improvements[indices[cursor + offset]]
            for offset in range(len(improvements))
        ]
        cursor += len(improvements)
        means.append(float(np.mean(sample)))
    ordered = np.sort(np.array(means, dtype=float))
    return {
        "entities": len(improvements),
        "mean_improvement": float(np.mean(improvements)),
        "lower_95": float(ordered[int(np.floor(0.025 * (replicates - 1)))]),
        "upper_95": float(ordered[int(np.ceil(0.975 * (replicates - 1)))]),
        "replicates": replicates,
        "seed": BOOTSTRAP_SEED,
    }
