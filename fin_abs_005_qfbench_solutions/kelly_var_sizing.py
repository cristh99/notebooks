from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

ASSETS = ("asset_0", "asset_1", "asset_2")


def clean_returns(path: Path, window: int | None) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = sorted({"date", *ASSETS} - set(frame.columns))
    if missing:
        raise ValueError(f"returns input missing columns: {missing}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ASSETS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna(subset=["date", *ASSETS])
    # A simple return cannot be <= -100%; values beyond +/-100% are treated
    # as production-feed corruption rather than financial observations.
    valid = np.ones(len(frame), dtype=bool)
    for column in ASSETS:
        valid &= frame[column].to_numpy(dtype=float) > -1.0
        valid &= np.abs(frame[column].to_numpy(dtype=float)) <= 1.0
    frame = frame.loc[valid].sort_values("date", kind="mergesort")
    frame = frame.drop_duplicates("date", keep="last")
    if window is not None and window > 0:
        frame = frame.tail(int(window))
    if len(frame) < 3:
        raise ValueError("not enough valid observations for covariance estimation")
    return frame.reset_index(drop=True)


def parametric_var(
    fractions: np.ndarray,
    mean_excess: np.ndarray,
    covariance: np.ndarray,
    confidence: float,
) -> float:
    mean = float(fractions @ mean_excess)
    volatility = float(
        math.sqrt(max(fractions @ covariance @ fractions, 0.0))
    )
    return float(norm.ppf(confidence) * volatility - mean)


def simulated_scheme(
    draws: np.ndarray,
    fractions: np.ndarray,
    initial_capital: float,
    risk_free_daily: float,
) -> dict[str, float | np.ndarray]:
    risky_excess = draws - risk_free_daily
    daily = risk_free_daily + np.einsum("pda,a->pd", risky_excess, fractions)
    growth = 1.0 + daily
    wealth = initial_capital * np.cumprod(growth, axis=1)
    terminal = wealth[:, -1]
    flattened = daily.reshape(-1)
    std = float(np.std(flattened, ddof=1))
    sharpe = (
        float(np.mean(flattened) / std * math.sqrt(252.0))
        if std > 0
        else 0.0
    )
    initial = np.full((wealth.shape[0], 1), initial_capital, dtype=float)
    full_wealth = np.concatenate([initial, wealth], axis=1)
    peaks = np.maximum.accumulate(full_wealth, axis=1)
    drawdowns = np.where(
        peaks > 0.0,
        (peaks - full_wealth) / peaks,
        0.0,
    )
    maximum_drawdown = np.max(drawdowns, axis=1)
    return {
        "terminal": terminal,
        "mean_terminal": float(np.mean(terminal)),
        "median_terminal": float(np.median(terminal)),
        "sharpe": sharpe,
        "p50_drawdown": float(np.median(maximum_drawdown)),
    }


def main() -> None:
    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    output = Path(os.environ.get("OUTPUT_DIR", "/app/output"))
    output.mkdir(parents=True, exist_ok=True)
    params = json.loads((data_dir / "params.json").read_text(encoding="utf-8"))
    window = params.get("estimation_window_days")
    frame = clean_returns(
        data_dir / "returns.csv",
        int(window) if window is not None else None,
    )
    values = frame.loc[:, ASSETS].to_numpy(dtype=float)
    risk_free_daily = float(params["risk_free_annual"]) / 252.0
    mean_returns = values.mean(axis=0)
    mean_excess = mean_returns - risk_free_daily
    covariance = np.cov(values, rowvar=False, ddof=1)
    covariance = np.asarray(covariance, dtype=float)
    kelly = np.linalg.pinv(covariance, rcond=1e-12) @ mean_excess
    portfolio_var_full = parametric_var(
        kelly,
        mean_excess,
        covariance,
        float(params["confidence_level"]),
    )
    max_var = float(params["max_var_daily"])
    if portfolio_var_full <= 0.0:
        var_scale = 1.0
    else:
        var_scale = min(1.0, max_var / portfolio_var_full)
    var_kelly = kelly * var_scale
    half_kelly = 0.5 * kelly
    equal_weight = np.ones(len(ASSETS), dtype=float) / len(ASSETS)

    rng = np.random.default_rng(int(params["seed"]))
    draws = rng.multivariate_normal(
        mean_returns,
        covariance,
        size=(int(params["n_simulation_paths"]), int(params["n_days"])),
        check_valid="raise",
        method="svd",
    )
    initial_capital = float(params["initial_capital"])
    schemes = {
        "full": simulated_scheme(
            draws, kelly, initial_capital, risk_free_daily
        ),
        "half": simulated_scheme(
            draws, half_kelly, initial_capital, risk_free_daily
        ),
        "var": simulated_scheme(
            draws, var_kelly, initial_capital, risk_free_daily
        ),
        "equal": simulated_scheme(
            draws, equal_weight, initial_capital, risk_free_daily
        ),
    }

    results = {
        "num_valid_observations": int(len(frame)),
        "median_terminal_wealth_full": schemes["full"]["median_terminal"],
        "median_terminal_wealth_var": schemes["var"]["median_terminal"],
        "sharpe_full": schemes["full"]["sharpe"],
        "sharpe_var": schemes["var"]["sharpe"],
        "p50_drawdown_full": schemes["full"]["p50_drawdown"],
        "p50_drawdown_var": schemes["var"]["p50_drawdown"],
    }
    intermediates = {
        "mean_excess_0": {"value": float(mean_excess[0])},
        "mean_excess_1": {"value": float(mean_excess[1])},
        "mean_excess_2": {"value": float(mean_excess[2])},
        "cov_00": {"value": float(covariance[0, 0])},
        "cov_01": {"value": float(covariance[0, 1])},
        "cov_12": {"value": float(covariance[1, 2])},
        "kelly_fraction_0": {"value": float(kelly[0])},
        "kelly_fraction_1": {"value": float(kelly[1])},
        "kelly_fraction_2": {"value": float(kelly[2])},
        "total_kelly_leverage": {"value": float(np.abs(kelly).sum())},
        "portfolio_var_full": {"value": portfolio_var_full},
        "var_scale_factor": {"value": float(var_scale)},
        "mean_terminal_wealth_full": {
            "value": schemes["full"]["mean_terminal"]
        },
    }
    (output / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output / "solution.json").write_text(
        json.dumps(
            {"intermediates": intermediates},
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
