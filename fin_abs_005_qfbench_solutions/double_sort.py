from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

COST_RATE = 0.0015
N_BUCKETS = 5
REQUIRED = ("identifier", "date", "betabab_1260d", "ret_12_7", "ret_lead1m")


def deterministic_bucket(values: pd.Series, identifiers: pd.Series) -> pd.Series:
    order = pd.DataFrame(
        {
            "value": pd.to_numeric(values, errors="coerce"),
            "identifier": pd.to_numeric(identifiers, errors="raise").astype(int),
        },
        index=values.index,
    ).sort_values(["value", "identifier"], kind="mergesort")
    n = len(order)
    if n < N_BUCKETS:
        return pd.Series(index=values.index, dtype="Int64")
    # Equivalent to a dependent quintile sort on unique deterministic ranks.
    buckets = np.floor(np.arange(n, dtype=float) * N_BUCKETS / n).astype(int)
    buckets = np.minimum(buckets, N_BUCKETS - 1)
    result = pd.Series(buckets, index=order.index, dtype="int64")
    return result.reindex(values.index)


def main() -> None:
    input_path = Path(
        os.environ.get("DOUBLE_SORT_DATA", "/app/data/stock_data.parquet")
    )
    output_dir = Path(os.environ.get("OUTPUT_DIR", "/app/output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.read_parquet(input_path)
    missing = sorted(set(REQUIRED) - set(frame.columns))
    if missing:
        raise ValueError(f"input missing required columns: {missing}")
    data = frame.loc[:, REQUIRED].copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    data["identifier"] = pd.to_numeric(
        data["identifier"], errors="raise"
    ).astype(int)
    for column in ("betabab_1260d", "ret_12_7", "ret_lead1m"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
        data.loc[~np.isfinite(data[column]), column] = np.nan
    data = data.sort_values(["date", "identifier"], kind="mergesort")
    if data.duplicated(["date", "identifier"]).any():
        raise ValueError("duplicate identifier/date observations are not permitted")

    previous: dict[int, float] | None = None
    output: list[dict[str, object]] = []
    for formation_date, month in data.groupby("date", sort=True):
        eligible = month.dropna(
            subset=["betabab_1260d", "ret_12_7", "ret_lead1m"]
        ).copy()
        if len(eligible) < N_BUCKETS:
            continue
        eligible["beta_bucket"] = deterministic_bucket(
            eligible["betabab_1260d"], eligible["identifier"]
        )
        low_beta = eligible.loc[eligible["beta_bucket"] == 0].copy()
        if len(low_beta) < N_BUCKETS:
            continue
        low_beta["momentum_bucket"] = deterministic_bucket(
            low_beta["ret_12_7"], low_beta["identifier"]
        )
        corner = low_beta.loc[
            low_beta["momentum_bucket"] == N_BUCKETS - 1
        ].copy()
        if corner.empty:
            continue
        corner = corner.sort_values("identifier", kind="mergesort")
        weight = 1.0 / len(corner)
        current = {
            int(identifier): weight for identifier in corner["identifier"]
        }
        gross = float(corner["ret_lead1m"].mean())
        if previous is None:
            turnover = 1.0
        else:
            names = set(previous) | set(current)
            turnover = float(
                sum(abs(current.get(name, 0.0) - previous.get(name, 0.0)) for name in names)
            )
        net = gross - COST_RATE * turnover
        output.append(
            {
                "date": pd.Timestamp(formation_date).date().isoformat(),
                "net_return": net,
            }
        )
        previous = current

    result = pd.DataFrame(output, columns=["date", "net_return"])
    if result.empty:
        raise ValueError("the dependent double sort emitted no portfolios")
    result = result.sort_values("date", kind="mergesort")
    result.to_csv(
        output_dir / "strategy_returns.csv",
        index=False,
        float_format="%.17g",
        lineterminator="\n",
    )


if __name__ == "__main__":
    main()
