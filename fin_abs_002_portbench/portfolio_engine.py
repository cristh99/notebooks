from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .audit import asset_class, asset_prefix, file_sha256

TRADING_COST_RATE = 0.0015
MIN_HISTORY = 252
MAX_HISTORY = 756
ASSET_CAP = 0.10
CLASS_CAP = 0.35
NO_TRADE_L1 = 0.10
PARTIAL_ADJUSTMENT = 0.50
SURVIVAL_CASH_SHIFT = 0.25
SURVIVAL_DRAWDOWN_TRIGGER = -0.08
SURVIVAL_VOL_TRIGGER = 0.25


@dataclass(frozen=True)
class MarketData:
    returns: pd.DataFrame
    class_map: dict[str, str]
    split: pd.Series
    dataset_sha256: str
    embedded_split_columns: tuple[str, ...]


@dataclass(frozen=True)
class BacktestResult:
    strategy: str
    start: str
    end: str
    daily: pd.DataFrame
    weights: pd.DataFrame
    metrics: dict[str, float | int | None]
    pit_violations: int


Strategy = Callable[
    [pd.DataFrame, Sequence[str], Mapping[str, str], np.ndarray],
    np.ndarray,
]


def load_market(path: Path) -> MarketData:
    frame = pd.read_csv(path, low_memory=False)
    dates = pd.to_datetime(frame.pop("date"), errors="raise")
    frame.index = dates
    return_columns = sorted(
        column
        for column in frame.columns
        if column.endswith("_return")
        and f"{asset_prefix(column)}_close" in frame.columns
    )
    assets = [asset_prefix(column) for column in return_columns]
    returns = frame[return_columns].copy()
    returns.columns = assets
    returns = returns.apply(pd.to_numeric, errors="coerce").astype(float)
    split_columns = tuple(
        column
        for column in frame.columns
        if column == "split" or column.endswith("_split")
    )
    years = returns.index.year
    split = pd.Series(
        np.select(
            [years <= 2022, years == 2023, years >= 2024],
            ["train", "val", "test"],
            default="invalid",
        ),
        index=returns.index,
        dtype="object",
    )
    classes = {asset: asset_class(asset) for asset in assets}
    return MarketData(
        returns=returns,
        class_map=classes,
        split=split,
        dataset_sha256=file_sha256(path),
        embedded_split_columns=split_columns,
    )


def normalize(weights: np.ndarray) -> np.ndarray:
    value = np.asarray(weights, dtype=float).copy()
    value[~np.isfinite(value)] = 0.0
    value = np.maximum(value, 0.0)
    total = float(value.sum())
    if total <= 0:
        return np.ones(len(value), dtype=float) / max(len(value), 1)
    return value / total


def eligible_assets(history: pd.DataFrame) -> list[str]:
    if history.empty:
        return []
    required = max(MIN_HISTORY, int(np.ceil(0.80 * len(history))))
    counts = history.notna().sum()
    recent = history.tail(5).notna().sum()
    return sorted(
        column
        for column in history.columns
        if int(counts[column]) >= required and int(recent[column]) >= 1
    )


def clean_history(history: pd.DataFrame, eligible: Sequence[str]) -> pd.DataFrame:
    selected = history[list(eligible)].copy()
    selected = selected.replace([np.inf, -np.inf], np.nan)
    return selected.fillna(0.0)


def covariance(history: pd.DataFrame, shrink: float = 0.0) -> np.ndarray:
    if history.shape[1] == 1:
        variance = float(history.iloc[:, 0].var(ddof=1))
        return np.array([[max(variance, 1e-10)]], dtype=float)
    matrix = history.cov().to_numpy(dtype=float)
    diagonal = np.diag(np.diag(matrix))
    matrix = (1.0 - shrink) * matrix + shrink * diagonal
    matrix = (matrix + matrix.T) / 2.0
    values, vectors = np.linalg.eigh(matrix)
    floor = max(float(np.nanmedian(np.diag(matrix))) * 1e-8, 1e-12)
    values = np.maximum(values, floor)
    return vectors @ np.diag(values) @ vectors.T


def risk_parity_weights(cov: np.ndarray, max_iter: int = 800) -> np.ndarray:
    n = cov.shape[0]
    if n == 1:
        return np.ones(1)
    weights = np.ones(n, dtype=float) / n
    for _ in range(max_iter):
        sigma_w = cov @ weights
        variance = float(weights @ sigma_w)
        if variance <= 0:
            break
        contributions = weights * sigma_w
        target = variance / n
        safe = np.maximum(contributions, 1e-18)
        updated = normalize(weights * np.sqrt(np.clip(target / safe, 0.2, 5.0)))
        if float(np.max(np.abs(updated - weights))) < 1e-10:
            weights = updated
            break
        weights = updated
    return normalize(weights)


def min_variance_weights(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    if n == 1:
        return np.ones(1)
    initial = np.ones(n, dtype=float) / n

    def objective(weights: np.ndarray) -> float:
        return float(weights @ cov @ weights)

    def gradient(weights: np.ndarray) -> np.ndarray:
        return 2.0 * cov @ weights

    try:
        result = minimize(
            objective,
            initial,
            jac=gradient,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * n,
            constraints=[{"type": "eq", "fun": lambda w: float(w.sum() - 1.0)}],
            options={"ftol": 1e-10, "maxiter": 300, "disp": False},
        )
        if result.success and np.isfinite(result.x).all():
            return normalize(result.x)
    except (ValueError, np.linalg.LinAlgError, FloatingPointError):
        pass
    inverse = np.linalg.pinv(cov + np.eye(n) * 1e-8)
    return normalize(np.maximum(inverse @ np.ones(n), 0.0))


def black_litterman_weights(history: pd.DataFrame) -> np.ndarray:
    n = history.shape[1]
    if n < 2:
        return np.ones(max(n, 1))
    cov = covariance(history, shrink=0.0)
    ridge = np.eye(n) * 1e-4 * max(float(np.mean(np.diag(cov))), 1e-10)
    cov = cov + ridge
    prior = history.mean().to_numpy(dtype=float)
    trailing = (1.0 + history).prod(axis=0).to_numpy(dtype=float) - 1.0
    active = np.flatnonzero(np.abs(trailing) > 0.01)
    if len(active) == 0:
        return np.ones(n) / n
    pick = np.zeros((len(active), n), dtype=float)
    pick[np.arange(len(active)), active] = 1.0
    views = np.sign(trailing[active]) * 0.01
    tau = 1.0 / max(len(history), 1)
    omega = np.diag(np.diag(pick @ (tau * cov) @ pick.T))
    omega = omega + np.eye(len(active)) * 1e-8
    try:
        tau_inv = np.linalg.pinv(tau * cov)
        omega_inv = np.linalg.pinv(omega)
        posterior_cov_inv = tau_inv + pick.T @ omega_inv @ pick
        posterior = np.linalg.pinv(posterior_cov_inv) @ (
            tau_inv @ prior + pick.T @ omega_inv @ views
        )
    except np.linalg.LinAlgError:
        return np.ones(n) / n

    def objective(weights: np.ndarray) -> float:
        expected = float(weights @ posterior)
        risk = float(np.sqrt(max(weights @ cov @ weights, 1e-12)))
        return -expected / risk

    try:
        result = minimize(
            objective,
            np.ones(n) / n,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * n,
            constraints=[{"type": "eq", "fun": lambda w: float(w.sum() - 1.0)}],
            options={"ftol": 1e-9, "maxiter": 300, "disp": False},
        )
        if result.success:
            return normalize(result.x)
    except (ValueError, FloatingPointError):
        pass
    return np.ones(n) / n


def proportional_with_caps(
    raw: np.ndarray,
    total: float,
    caps: np.ndarray,
) -> np.ndarray:
    """Allocate an exact total proportionally while respecting upper bounds."""
    raw = np.maximum(np.asarray(raw, dtype=float), 0.0)
    caps = np.maximum(np.asarray(caps, dtype=float), 0.0)
    if total < -1e-12 or total > float(caps.sum()) + 1e-10:
        raise ValueError("requested total exceeds declared capacity")
    output = np.zeros(len(raw), dtype=float)
    active = caps > 1e-14
    remaining = float(max(total, 0.0))
    for _ in range(len(raw) + 1):
        if remaining <= 1e-12:
            break
        indices = np.flatnonzero(active)
        if len(indices) == 0:
            break
        scores = raw[indices]
        if float(scores.sum()) <= 1e-18:
            scores = np.ones(len(indices), dtype=float)
        proposal = remaining * scores / float(scores.sum())
        capacity = caps[indices] - output[indices]
        capped = proposal >= capacity - 1e-14
        if not capped.any():
            output[indices] += proposal
            remaining = 0.0
            break
        capped_indices = indices[capped]
        additions = np.maximum(caps[capped_indices] - output[capped_indices], 0.0)
        output[capped_indices] += additions
        remaining -= float(additions.sum())
        active[capped_indices] = False
    if remaining > 1e-8:
        raise ValueError("water-filling could not allocate declared total")
    return output


def bounded_capacity(
    assets: Sequence[str],
    class_map: Mapping[str, str],
    *,
    asset_cap: float = ASSET_CAP,
    class_cap: float = CLASS_CAP,
) -> float:
    classes = sorted(set(class_map[asset] for asset in assets))
    return float(
        sum(
            min(
                class_cap,
                sum(class_map[asset] == name for asset in assets) * asset_cap,
            )
            for name in classes
        )
    )


def capped_weights(
    raw: np.ndarray,
    assets: Sequence[str],
    class_map: Mapping[str, str],
    *,
    asset_cap: float = ASSET_CAP,
    class_cap: float = CLASS_CAP,
) -> np.ndarray:
    if bounded_capacity(
        assets, class_map, asset_cap=asset_cap, class_cap=class_cap
    ) < 1.0 - 1e-10:
        raise ValueError("eligible universe cannot satisfy declared caps")
    target = normalize(raw)
    classes = sorted(set(class_map[asset] for asset in assets))
    class_indices = {
        name: np.array([class_map[asset] == name for asset in assets], dtype=bool)
        for name in classes
    }
    class_raw = np.array(
        [float(target[indices].sum()) for indices in class_indices.values()],
        dtype=float,
    )
    class_capacity = np.array(
        [min(class_cap, int(indices.sum()) * asset_cap) for indices in class_indices.values()],
        dtype=float,
    )
    class_weights = proportional_with_caps(class_raw, 1.0, class_capacity)
    output = np.zeros(len(target), dtype=float)
    for class_weight, indices in zip(
        class_weights, class_indices.values(), strict=True
    ):
        positions = np.flatnonzero(indices)
        within = proportional_with_caps(
            target[positions],
            float(class_weight),
            np.full(len(positions), asset_cap, dtype=float),
        )
        output[positions] = within
    if not np.isclose(output.sum(), 1.0, atol=1e-9):
        raise ValueError("bounded allocation does not sum to one")
    if float(output.max()) > asset_cap + 1e-9:
        raise ValueError("bounded allocation exceeds asset cap")
    for indices in class_indices.values():
        if float(output[indices].sum()) > class_cap + 1e-9:
            raise ValueError("bounded allocation exceeds class cap")
    return output


def align_previous(
    previous_full: np.ndarray,
    all_assets: Sequence[str],
    eligible: Sequence[str],
) -> np.ndarray:
    positions = {asset: index for index, asset in enumerate(all_assets)}
    value = np.array([previous_full[positions[asset]] for asset in eligible], dtype=float)
    return normalize(value) if float(value.sum()) > 0 else np.ones(len(eligible)) / len(eligible)


def expand_weights(
    selected: np.ndarray,
    eligible: Sequence[str],
    all_assets: Sequence[str],
) -> np.ndarray:
    positions = {asset: index for index, asset in enumerate(all_assets)}
    full = np.zeros(len(all_assets), dtype=float)
    for weight, asset in zip(selected, eligible, strict=True):
        full[positions[asset]] = float(weight)
    return normalize(full)


def _base_target(
    name: str,
    history: pd.DataFrame,
    eligible: Sequence[str],
    class_map: Mapping[str, str],
) -> np.ndarray:
    cleaned = clean_history(history, eligible)
    if name == "equal_weight":
        return np.ones(len(eligible)) / len(eligible)
    if name == "sixty_forty":
        weights = np.zeros(len(eligible), dtype=float)
        equity = np.array([class_map[asset] == "equities" for asset in eligible])
        bonds = np.array([class_map[asset] == "bonds" for asset in eligible])
        if equity.any() and bonds.any():
            weights[equity] = 0.60 / int(equity.sum())
            weights[bonds] = 0.40 / int(bonds.sum())
            return weights
        return np.ones(len(eligible)) / len(eligible)
    if name == "risk_parity":
        volatility = cleaned.std(ddof=1).to_numpy(dtype=float)
        finite = volatility[np.isfinite(volatility) & (volatility > 1e-12)]
        fallback = float(np.median(finite)) if len(finite) else 1.0
        volatility = np.where(
            np.isfinite(volatility) & (volatility > 1e-12), volatility, fallback
        )
        return normalize(1.0 / volatility)
    if name == "cov_risk_parity":
        return risk_parity_weights(covariance(cleaned, shrink=0.0))
    if name == "min_variance":
        return min_variance_weights(covariance(cleaned, shrink=0.0))
    if name == "black_litterman":
        return black_litterman_weights(cleaned)
    if name in {"robust_erc", "robust_erc_ntb", "robust_survival"}:
        raw = risk_parity_weights(covariance(cleaned, shrink=0.50))
        return capped_weights(raw, eligible, class_map)
    raise ValueError(f"unknown strategy: {name}")


def target_weights(
    name: str,
    history: pd.DataFrame,
    all_assets: Sequence[str],
    class_map: Mapping[str, str],
    previous_full: np.ndarray,
) -> np.ndarray:
    eligible = eligible_assets(history)
    if not eligible:
        return previous_full.copy()
    robust = name in {"robust_erc", "robust_erc_ntb", "robust_survival"}
    if robust and bounded_capacity(eligible, class_map) < 1.0 - 1e-10:
        return previous_full.copy()
    selected = _base_target(name, history, eligible, class_map)
    previous = align_previous(previous_full, all_assets, eligible)
    if name in {"robust_erc_ntb", "robust_survival"}:
        distance = float(np.abs(selected - previous).sum())
        if distance <= NO_TRADE_L1:
            selected = previous
        else:
            selected = normalize(
                PARTIAL_ADJUSTMENT * selected
                + (1.0 - PARTIAL_ADJUSTMENT) * previous
            )
        selected = capped_weights(selected, eligible, class_map)
    if name == "robust_survival":
        prior = history[list(all_assets)].fillna(0.0).tail(60)
        prior_weights = previous_full.copy()
        if float(prior_weights.sum()) <= 0:
            prior_weights = expand_weights(selected, eligible, all_assets)
        portfolio_returns = prior.to_numpy(dtype=float) @ prior_weights
        wealth = np.cumprod(1.0 + portfolio_returns)
        peaks = np.maximum.accumulate(wealth) if len(wealth) else np.array([1.0])
        drawdown = float(np.min(wealth / peaks - 1.0)) if len(wealth) else 0.0
        volatility = (
            float(np.std(portfolio_returns, ddof=1) * np.sqrt(252))
            if len(portfolio_returns) > 1
            else 0.0
        )
        if drawdown <= SURVIVAL_DRAWDOWN_TRIGGER or volatility >= SURVIVAL_VOL_TRIGGER:
            cash_indices = np.array(
                [class_map[asset] == "cash" for asset in eligible], dtype=bool
            )
            if cash_indices.any():
                selected *= 1.0 - SURVIVAL_CASH_SHIFT
                selected[cash_indices] += SURVIVAL_CASH_SHIFT / int(
                    cash_indices.sum()
                )
                selected = capped_weights(selected, eligible, class_map)
    return expand_weights(selected, eligible, all_assets)


def first_month_dates(index: pd.DatetimeIndex) -> set[pd.Timestamp]:
    series = pd.Series(index=index, data=index)
    return set(series.groupby(index.to_period("M")).first().tolist())


def initial_cash_weights(
    returns: pd.DataFrame,
    class_map: Mapping[str, str],
    before: pd.Timestamp,
) -> np.ndarray:
    assets = list(returns.columns)
    history = returns.loc[returns.index < before].tail(MAX_HISTORY)
    cash_assets = [asset for asset in eligible_assets(history) if class_map[asset] == "cash"]
    weights = np.zeros(len(assets), dtype=float)
    if cash_assets:
        volatility = history[cash_assets].fillna(0.0).std(ddof=1)
        selected = str(volatility.idxmin())
        weights[assets.index(selected)] = 1.0
        return weights
    weights[:] = 1.0 / len(weights)
    return weights


def performance_metrics(
    daily: pd.DataFrame,
    weights: pd.DataFrame,
) -> dict[str, float | int | None]:
    returns = daily["net_return"].to_numpy(dtype=float)
    if len(returns) == 0:
        return {
            "observations": 0,
            "total_return": None,
            "annualized_return": None,
            "annualized_volatility": None,
            "sharpe": None,
            "max_drawdown_loss": None,
            "expected_shortfall_95_loss": None,
            "turnover": None,
            "total_cost": None,
            "maximum_single_asset_weight": None,
        }
    wealth = np.cumprod(1.0 + returns)
    total_return = float(wealth[-1] - 1.0)
    annualized_return = float(wealth[-1] ** (252.0 / len(returns)) - 1.0)
    volatility = float(np.std(returns, ddof=1) * np.sqrt(252)) if len(returns) > 1 else 0.0
    sharpe = (
        float(np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(252))
        if len(returns) > 1 and np.std(returns, ddof=1) > 1e-15
        else 0.0
    )
    peaks = np.maximum.accumulate(wealth)
    drawdown_loss = float(-np.min(wealth / peaks - 1.0))
    losses = -returns
    tail_count = max(1, int(np.ceil(0.05 * len(losses))))
    expected_shortfall = float(np.mean(np.sort(losses)[-tail_count:]))
    max_weight = (
        float(np.nanmax(weights.to_numpy(dtype=float))) if not weights.empty else 0.0
    )
    return {
        "observations": int(len(returns)),
        "total_return": total_return,
        "annualized_return": annualized_return,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown_loss": drawdown_loss,
        "expected_shortfall_95_loss": expected_shortfall,
        "turnover": float(daily["turnover"].sum()),
        "total_cost": float(daily["cost"].sum()),
        "maximum_single_asset_weight": max_weight,
    }


def run_backtest(
    market: MarketData,
    strategy: str,
    start: str,
    end: str,
) -> BacktestResult:
    all_assets = list(market.returns.columns)
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    evaluation = market.returns.loc[
        (market.returns.index >= start_date) & (market.returns.index <= end_date)
    ]
    if evaluation.empty:
        raise ValueError(f"empty evaluation window {start}/{end}")
    rebalance_dates = first_month_dates(evaluation.index)
    current = initial_cash_weights(market.returns, market.class_map, evaluation.index[0])
    daily_rows: list[dict[str, float | str]] = []
    weight_rows: list[np.ndarray] = []
    pit_violations = 0

    for date, row in evaluation.iterrows():
        turnover = 0.0
        cost = 0.0
        if date in rebalance_dates:
            history = market.returns.loc[market.returns.index < date].tail(MAX_HISTORY)
            if not history.empty and history.index.max() >= date:
                pit_violations += 1
            target = target_weights(
                strategy,
                history,
                all_assets,
                market.class_map,
                current,
            )
            turnover = 0.5 * float(np.abs(target - current).sum())
            cost = TRADING_COST_RATE * turnover
            current = target
        asset_returns = row.fillna(0.0).to_numpy(dtype=float)
        gross_return = float(current @ asset_returns)
        net_return = gross_return - cost
        daily_rows.append(
            {
                "date": date.date().isoformat(),
                "gross_return": gross_return,
                "net_return": net_return,
                "turnover": turnover,
                "cost": cost,
            }
        )
        weight_rows.append(current.copy())
        denominator = 1.0 + gross_return
        if denominator > 1e-12:
            current = normalize(current * (1.0 + asset_returns) / denominator)

    daily = pd.DataFrame(daily_rows)
    daily.index = pd.to_datetime(daily.pop("date"))
    weights = pd.DataFrame(weight_rows, index=daily.index, columns=all_assets)
    return BacktestResult(
        strategy=strategy,
        start=start,
        end=end,
        daily=daily,
        weights=weights,
        metrics=performance_metrics(daily, weights),
        pit_violations=pit_violations,
    )


def selection_key(result: BacktestResult) -> tuple[float, float, float, float, str]:
    metrics = result.metrics
    return (
        float(metrics["sharpe"] or -1e9),
        -float(metrics["max_drawdown_loss"] or 1e9),
        -float(metrics["expected_shortfall_95_loss"] or 1e9),
        -float(metrics["turnover"] or 1e9),
        result.strategy,
    )


def monthly_returns(daily: pd.DataFrame) -> pd.Series:
    return daily["net_return"].groupby(daily.index.to_period("M")).apply(
        lambda values: float(np.prod(1.0 + values.to_numpy(dtype=float)) - 1.0)
    )


def lcg_indices(seed: int, count: int, modulus: int) -> list[int]:
    state = seed & 0xFFFFFFFF
    output: list[int] = []
    for _ in range(count):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        output.append(state % modulus)
    return output


def moving_block_bootstrap_ci(
    differences: Sequence[float],
    *,
    block_length: int = 3,
    replicates: int = 5000,
    seed: int = 20260803,
) -> dict[str, float | int | None]:
    values = np.asarray(differences, dtype=float)
    n = len(values)
    if n == 0:
        return {"mean": None, "lower_95": None, "upper_95": None, "replicates": 0}
    blocks_per_sample = int(np.ceil(n / block_length))
    starts = lcg_indices(seed, replicates * blocks_per_sample, n)
    means: list[float] = []
    cursor = 0
    for _ in range(replicates):
        sample: list[float] = []
        for _ in range(blocks_per_sample):
            start = starts[cursor]
            cursor += 1
            sample.extend(values[(start + offset) % n] for offset in range(block_length))
        means.append(float(np.mean(sample[:n])))
    ordered = np.sort(np.asarray(means, dtype=float))
    low_index = int(np.floor(0.025 * (replicates - 1)))
    high_index = int(np.ceil(0.975 * (replicates - 1)))
    return {
        "mean": float(np.mean(values)),
        "lower_95": float(ordered[low_index]),
        "upper_95": float(ordered[high_index]),
        "replicates": replicates,
        "block_length": block_length,
        "seed": seed,
    }
