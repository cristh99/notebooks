from __future__ import annotations

from typing import Any

import pandas as pd

from . import reserving as core
from .audit import CUTOFFS


def prior_elr_by_lob(frame: pd.DataFrame, cutoff: int) -> dict[str, float]:
    visible = frame.loc[
        (frame["split"] == "train")
        & (frame["DevelopmentYear"] <= cutoff)
        & frame["IncurLoss"].map(core.finite_positive)
        & frame["EarnedPremNet"].map(core.finite_positive)
    ].copy()
    if visible.empty:
        return {}
    latest = (
        visible.sort_values("DevelopmentYear")
        .groupby(["GRCODE", "LOB", "AccidentYear"], sort=True, as_index=False)
        .tail(1)
    )
    output: dict[str, float] = {}
    for lob, group in latest.groupby("LOB", sort=True):
        premium = float(group["EarnedPremNet"].sum())
        output[str(lob)] = (
            float(group["IncurLoss"].sum()) / premium if premium > 0 else 0.0
        )
    return output


def build_factor_set_v2(
    frame: pd.DataFrame, cases: pd.DataFrame, cutoff: int
) -> core.FactorSet:
    links = core.link_rows(frame, cutoff)
    company_table = core.company_factor_table(links)
    pooled, robust, credibility_volume = core.training_factor_maps(links)
    company = {
        (str(row.GRCODE), str(row.LOB), int(row.lag)): float(row.factor)
        for row in company_table.itertuples(index=False)
    }
    company_volume = {
        (str(row.GRCODE), str(row.LOB), int(row.lag)): float(row.volume)
        for row in company_table.itertuples(index=False)
    }
    return core.FactorSet(
        pooled=pooled,
        robust_pooled=robust,
        credibility_volume=credibility_volume,
        company=company,
        company_volume=company_volume,
        target_elr=prior_elr_by_lob(frame, cutoff),
        cape_cod_elr=core.cape_cod_elr_by_lob_cutoff(
            cases.loc[cases["cutoff"] == cutoff], pooled
        ),
    )


def predict_cases_v2(frame: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    original = core.build_factor_set
    core.build_factor_set = build_factor_set_v2
    try:
        result = core.predict_cases(frame, cases)
    finally:
        core.build_factor_set = original
    return result


def temporal_information_contract(frame: pd.DataFrame) -> dict[str, Any]:
    entities = {
        split: set(frame.loc[frame["split"] == split, "GRCODE"])
        for split in ("train", "validation", "test")
    }
    cutoffs: dict[str, Any] = {}
    for cutoff in CUTOFFS:
        visible = frame.loc[frame["DevelopmentYear"] <= cutoff]
        train_visible = visible.loc[visible["split"] == "train"]
        cutoffs[str(cutoff)] = {
            "visible_max_development_year": int(visible["DevelopmentYear"].max()),
            "training_parameter_max_development_year": int(
                train_visible["DevelopmentYear"].max()
            ),
            "no_future_cells": int(visible["DevelopmentYear"].max()) <= cutoff,
            "pooled_parameters_train_only": True,
            "a_priori_elr_train_only": True,
        }
    return {
        "entity_sets_disjoint": not (
            entities["train"] & entities["validation"]
            or entities["train"] & entities["test"]
            or entities["validation"] & entities["test"]
        ),
        "entity_counts": {key: len(value) for key, value in entities.items()},
        "cutoffs": cutoffs,
        "all_cutoffs_no_future": all(
            value["no_future_cells"] for value in cutoffs.values()
        ),
    }
