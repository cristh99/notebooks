from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

SPOT_GRID = np.array([0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20])
MATURITY_GRID = np.array([0.25, 0.50, 1.00])
RISK_FREE = 0.05
DIVIDEND_YIELD = 0.013


def locate_close(frame: pd.DataFrame) -> str:
    normalized = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in ("close", "adj close", "adj_close", "adjusted_close"):
        if candidate in normalized:
            return normalized[candidate]
    raise ValueError("SPY input has no close-price column")


def calibrated_parameters(path: Path) -> dict[str, float | int]:
    frame = pd.read_csv(path)
    close_column = locate_close(frame)
    close = pd.to_numeric(frame[close_column], errors="coerce")
    close = close.replace([np.inf, -np.inf], np.nan).dropna()
    close = close.loc[close > 0]
    log_returns = np.log(close / close.shift(1)).dropna()
    if len(log_returns) < 2:
        raise ValueError("not enough valid prices to calibrate volatility")
    return_std = float(log_returns.std(ddof=1))
    sigma = return_std * math.sqrt(252.0)
    s0 = float(close.iloc[-1])
    return {
        "S0": s0,
        "sigma": sigma,
        "r": RISK_FREE,
        "D": DIVIDEND_YIELD,
        "K": s0,
        "n_returns": int(len(log_returns)),
        "return_mean": float(log_returns.mean()),
        "return_std": return_std,
    }


def point(S: float, K: float, T: float, sigma: float) -> dict[str, float]:
    r = RISK_FREE
    q = DIVIDEND_YIELD
    root_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (
        sigma * root_t
    )
    d2 = d1 - sigma * root_t
    df_r = math.exp(-r * T)
    df_q = math.exp(-q * T)
    phi = norm.pdf(d1)

    call = S * df_q * norm.cdf(d1) - K * df_r * norm.cdf(d2)
    put = K * df_r * norm.cdf(-d2) - S * df_q * norm.cdf(-d1)
    call_delta = df_q * norm.cdf(d1)
    put_delta = df_q * (norm.cdf(d1) - 1.0)
    gamma = df_q * phi / (S * sigma * root_t)
    vega = S * df_q * phi * root_t
    call_theta = (
        -S * df_q * phi * sigma / (2.0 * root_t)
        - r * K * df_r * norm.cdf(d2)
        + q * S * df_q * norm.cdf(d1)
    )
    put_theta = (
        -S * df_q * phi * sigma / (2.0 * root_t)
        + r * K * df_r * norm.cdf(-d2)
        - q * S * df_q * norm.cdf(-d1)
    )
    call_rho = K * T * df_r * norm.cdf(d2)
    put_rho = -K * T * df_r * norm.cdf(-d2)
    call_residual = (
        call_theta
        + (r - q) * S * call_delta
        + 0.5 * sigma * sigma * S * S * gamma
        - r * call
    )
    put_residual = (
        put_theta
        + (r - q) * S * put_delta
        + 0.5 * sigma * sigma * S * S * gamma
        - r * put
    )
    parity = abs(call - put - (S * df_q - K * df_r))
    return {
        "call_price": call,
        "put_price": put,
        "call_delta": call_delta,
        "put_delta": put_delta,
        "gamma": gamma,
        "call_theta": call_theta,
        "put_theta": put_theta,
        "vega": vega,
        "call_rho": call_rho,
        "put_rho": put_rho,
        "call_pde_residual": call_residual,
        "put_pde_residual": put_residual,
        "parity_error": parity,
    }


def main() -> None:
    input_path = Path(os.environ.get("SPY_DATA", "/app/spy_daily.csv"))
    output = Path(os.environ.get("OUTPUT_DIR", "./output"))
    output.mkdir(parents=True, exist_ok=True)
    calibration = calibrated_parameters(input_path)
    sigma = float(calibration["sigma"])
    strike = float(calibration["K"])

    surface_rows: list[dict[str, float]] = []
    verification_rows: list[dict[str, float]] = []
    for maturity in MATURITY_GRID:
        for moneyness in SPOT_GRID:
            spot = float(moneyness * strike)
            values = point(spot, strike, float(maturity), sigma)
            surface_rows.append(
                {
                    "T": float(maturity),
                    "moneyness": float(moneyness),
                    "S": spot,
                    **{
                        key: values[key]
                        for key in (
                            "call_price",
                            "put_price",
                            "call_delta",
                            "put_delta",
                            "gamma",
                            "call_theta",
                            "put_theta",
                            "vega",
                            "call_rho",
                            "put_rho",
                        )
                    },
                }
            )
            verification_rows.append(
                {
                    "T": float(maturity),
                    "moneyness": float(moneyness),
                    "S": spot,
                    "call_pde_residual": values["call_pde_residual"],
                    "put_pde_residual": values["put_pde_residual"],
                    "parity_error": values["parity_error"],
                }
            )

    surface = pd.DataFrame(surface_rows).sort_values(["T", "moneyness"])
    verification = pd.DataFrame(verification_rows).sort_values(
        ["T", "moneyness"]
    )
    surface.to_csv(output / "greeks_surface.csv", index=False, float_format="%.17g")
    verification.to_csv(
        output / "pde_verification.csv", index=False, float_format="%.17g"
    )
    (output / "calibration.json").write_text(
        json.dumps(calibration, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    def atm(maturity: float) -> pd.Series:
        return surface.loc[
            np.isclose(surface["T"], maturity)
            & np.isclose(surface["moneyness"], 1.0)
        ].iloc[0]

    t025 = atm(0.25)
    t050 = atm(0.50)
    t100 = atm(1.00)
    gamma_t050 = surface.loc[np.isclose(surface["T"], 0.50)]
    summary = {
        "n_grid_points": 27,
        "n_maturities": 3,
        "n_moneyness": 9,
        "max_call_pde_residual": float(
            verification["call_pde_residual"].abs().max()
        ),
        "max_put_pde_residual": float(
            verification["put_pde_residual"].abs().max()
        ),
        "max_parity_error": float(verification["parity_error"].max()),
        "atm_call_price_T025": float(t025["call_price"]),
        "atm_call_price_T050": float(t050["call_price"]),
        "atm_call_price_T100": float(t100["call_price"]),
        "atm_call_delta_T100": float(t100["call_delta"]),
        "atm_gamma_T100": float(t100["gamma"]),
        "atm_vega_T100": float(t100["vega"]),
        "max_gamma_moneyness_T050": float(
            gamma_t050.loc[gamma_t050["gamma"].idxmax(), "moneyness"]
        ),
        "delta_call_range_valid": bool(
            np.all(surface["call_delta"] >= -1e-15)
            and np.all(
                surface["call_delta"]
                <= np.exp(-DIVIDEND_YIELD * surface["T"]) + 1e-15
            )
        ),
        "gamma_positive_everywhere": bool(np.all(surface["gamma"] > 0.0)),
        "vega_positive_everywhere": bool(np.all(surface["vega"] > 0.0)),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
