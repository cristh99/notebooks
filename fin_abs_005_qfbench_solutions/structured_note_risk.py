from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model
from scipy.optimize import brentq, minimize_scalar
from scipy.stats import norm

TRADING_DAYS = 252.0
CONFIDENCE = 0.99


def clean_log_returns(path: Path) -> np.ndarray:
    frame = pd.read_csv(path)
    if "log_return" not in frame.columns:
        raise ValueError("returns input has no log_return column")
    values = pd.to_numeric(frame["log_return"], errors="coerce")
    values = values.replace([np.inf, -np.inf], np.nan).dropna()
    values = values.loc[np.abs(values) <= 1.0]
    if len(values) < 100:
        raise ValueError("not enough valid log returns for GARCH estimation")
    return values.to_numpy(dtype=float)


def fit_garch(returns: np.ndarray) -> dict[str, float]:
    scaled = returns * 100.0
    model = arch_model(
        scaled,
        mean="Zero",
        vol="GARCH",
        p=1,
        o=0,
        q=1,
        dist="normal",
        rescale=False,
    )
    fit = model.fit(
        disp="off",
        show_warning=False,
        tol=1e-10,
        options={"maxiter": 5000},
    )
    omega_pct = float(fit.params["omega"])
    alpha = float(fit.params["alpha[1]"])
    beta = float(fit.params["beta[1]"])
    persistence = alpha + beta
    if not (omega_pct > 0.0 and 0.0 <= persistence < 1.0):
        raise ValueError("GARCH fit is not covariance-stationary")
    forecast_pct_variance = float(
        fit.forecast(horizon=1, reindex=False).variance.iloc[-1, 0]
    )
    omega = omega_pct / 10000.0
    forecast_daily_variance = forecast_pct_variance / 10000.0
    long_run_variance = omega / (1.0 - persistence)
    annual_volatility = math.sqrt(forecast_daily_variance * TRADING_DAYS)
    return {
        "omega": omega,
        "alpha": alpha,
        "beta": beta,
        "persistence": persistence,
        "long_run_variance": long_run_variance,
        "forecast_daily_variance": forecast_daily_variance,
        "annual_volatility": annual_volatility,
    }


def down_and_out_call(
    spot: float,
    strike: float,
    barrier: float,
    rate: float,
    maturity: float,
    volatility: float,
    dividend_yield: float = 0.0,
) -> float:
    if maturity <= 0.0:
        return max(spot - strike, 0.0) if spot > barrier else 0.0
    if volatility <= 0.0:
        terminal = spot * math.exp((rate - dividend_yield) * maturity)
        payoff = max(terminal - strike, 0.0)
        return math.exp(-rate * maturity) * payoff if spot > barrier else 0.0
    if spot <= barrier:
        return 0.0
    if barrier >= strike:
        raise ValueError("this task requires a down barrier below the strike")
    root_t = math.sqrt(maturity)
    sigma_root = volatility * root_t
    lam = (rate - dividend_yield + 0.5 * volatility * volatility) / (
        volatility * volatility
    )
    x1 = math.log(spot / strike) / sigma_root + lam * sigma_root
    y1 = math.log(barrier * barrier / (spot * strike)) / sigma_root + lam * sigma_root
    hs = barrier / spot
    first = (
        spot * math.exp(-dividend_yield * maturity) * norm.cdf(x1)
        - strike * math.exp(-rate * maturity) * norm.cdf(x1 - sigma_root)
    )
    image = (
        spot
        * math.exp(-dividend_yield * maturity)
        * hs ** (2.0 * lam)
        * norm.cdf(y1)
        - strike
        * math.exp(-rate * maturity)
        * hs ** (2.0 * lam - 2.0)
        * norm.cdf(y1 - sigma_root)
    )
    return max(float(first - image), 0.0)


def option_delta(
    spot: float,
    strike: float,
    barrier: float,
    rate: float,
    maturity: float,
    volatility: float,
) -> float:
    step = max(spot * 1e-4, 1e-5)
    if spot - 2.0 * step <= barrier:
        step = max((spot - barrier) / 4.1, 1e-7)
    values = [
        down_and_out_call(
            spot + multiple * step,
            strike,
            barrier,
            rate,
            maturity,
            volatility,
        )
        for multiple in (-2.0, -1.0, 1.0, 2.0)
    ]
    return float((values[0] - 8.0 * values[1] + 8.0 * values[2] - values[3]) / (12.0 * step))


def fair_value_at_volatility(params: dict[str, float], volatility: float) -> tuple[float, ...]:
    notional = float(params["notional"])
    spot = float(params["S0"])
    strike = float(params["K"])
    barrier = float(params["B"])
    rate = float(params["r"])
    maturity = float(params["T"])
    participation = float(params["participation"])
    bond_pv = notional * math.exp(-rate * maturity)
    unit_price = down_and_out_call(
        spot, strike, barrier, rate, maturity, volatility
    )
    n_options = participation * notional / spot
    option_value = n_options * unit_price
    return bond_pv + option_value, bond_pv, unit_price, option_value, n_options


def breakeven_volatility(params: dict[str, float]) -> float:
    notional = float(params["notional"])

    def objective(volatility: float) -> float:
        return fair_value_at_volatility(params, volatility)[0] - notional

    grid = np.geomspace(1e-4, 5.0, 300)
    values = [objective(float(value)) for value in grid]
    for left, right, left_value, right_value in zip(
        grid[:-1], grid[1:], values[:-1], values[1:], strict=True
    ):
        if left_value == 0.0:
            return float(left)
        if left_value * right_value < 0.0:
            return float(brentq(objective, float(left), float(right), xtol=1e-12))
    result = minimize_scalar(
        lambda volatility: abs(objective(float(volatility))),
        bounds=(1e-4, 5.0),
        method="bounded",
        options={"xatol": 1e-12},
    )
    return float(result.x)


def main() -> None:
    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    output = Path(os.environ.get("OUTPUT_DIR", "/app/output"))
    output.mkdir(parents=True, exist_ok=True)
    returns = clean_log_returns(data_dir / "returns.csv")
    params = json.loads((data_dir / "params.json").read_text(encoding="utf-8"))
    garch = fit_garch(returns)
    volatility = garch["annual_volatility"]
    fair_value, bond_pv, unit_price, option_value, n_options = fair_value_at_volatility(
        params, volatility
    )
    delta = option_delta(
        float(params["S0"]),
        float(params["K"]),
        float(params["B"]),
        float(params["r"]),
        float(params["T"]),
        volatility,
    )
    note_delta = n_options * delta
    daily_volatility = math.sqrt(garch["forecast_daily_variance"])
    dollar_sigma = abs(note_delta * float(params["S0"])) * daily_volatility
    z_value = float(norm.ppf(CONFIDENCE))
    note_var = z_value * dollar_sigma
    note_es = float(norm.pdf(z_value) / (1.0 - CONFIDENCE) * dollar_sigma)
    breakeven = breakeven_volatility(params)
    notional = float(params["notional"])

    results = {
        "fair_value": fair_value,
        "markup_pct": (notional - fair_value) / notional * 100.0,
        "note_var_99": note_var,
        "note_es_99": note_es,
        "breakeven_vol": breakeven,
        "garch_persistence": garch["persistence"],
        "long_run_variance": garch["long_run_variance"],
        "garch_vol": volatility,
        "bond_pv": bond_pv,
        "option_unit_price": unit_price,
        "option_value": option_value,
        "n_options": n_options,
        "option_delta": delta,
        "note_delta": note_delta,
    }
    intermediates = {
        "garch_omega": {"value": garch["omega"]},
        "garch_alpha": {"value": garch["alpha"]},
        "garch_beta": {"value": garch["beta"]},
        "garch_persistence": {"value": garch["persistence"]},
        "long_run_variance": {"value": garch["long_run_variance"]},
        "garch_vol": {"value": volatility},
        "bond_pv": {"value": bond_pv},
        "option_unit_price": {"value": unit_price},
        "option_value": {"value": option_value},
        "n_options": {"value": n_options},
        "option_delta": {"value": delta},
        "note_delta": {"value": note_delta},
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
