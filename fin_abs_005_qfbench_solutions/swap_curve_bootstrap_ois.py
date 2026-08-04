from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from scipy.optimize import brentq


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def add_months(value: date, months: int) -> date:
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(value.day, last_day))


def add_business_days(value: date, days: int) -> date:
    result = value
    added = 0
    while added < days:
        result += timedelta(days=1)
        if result.weekday() < 5:
            added += 1
    return result


def act_360(start: date, end: date) -> float:
    return (end - start).days / 360.0


def act_36525(start: date, end: date) -> float:
    return (end - start).days / 365.25


def thirty_360(start: date, end: date) -> float:
    d1 = min(start.day, 30)
    d2 = 30 if d1 == 30 and end.day == 31 else min(end.day, 30)
    return (
        360 * (end.year - start.year)
        + 30 * (end.month - start.month)
        + d2
        - d1
    ) / 360.0


def schedule(effective: date, maturity: date, months: int) -> list[date]:
    dates = [maturity]
    while True:
        previous = add_months(dates[-1], -months)
        if previous <= effective:
            break
        dates.append(previous)
    dates.reverse()
    return dates


@dataclass(frozen=True)
class Pillar:
    time: float
    discount_factor: float
    maturity: date
    tenor: str


@dataclass
class Curve:
    valuation_date: date
    pillars: list[Pillar]

    def pairs(self) -> list[tuple[float, float]]:
        return [(pillar.time, pillar.discount_factor) for pillar in self.pillars]

    def df(self, target: date) -> float:
        return interpolate_df(self.pairs(), act_36525(self.valuation_date, target))

    def zero(self, target: date) -> float:
        time = act_36525(self.valuation_date, target)
        if time <= 0.0:
            return 0.0
        return -math.log(self.df(target)) / time


def interpolate_df(pairs: Iterable[tuple[float, float]], time: float) -> float:
    values = sorted((float(t), float(df)) for t, df in pairs)
    if time <= 0.0 or not values:
        return 1.0
    if time <= values[0][0]:
        zero = -math.log(values[0][1]) / values[0][0]
        return math.exp(-zero * time)
    if time >= values[-1][0]:
        zero = -math.log(values[-1][1]) / values[-1][0]
        return math.exp(-zero * time)
    for (left_t, left_df), (right_t, right_df) in zip(
        values[:-1], values[1:], strict=True
    ):
        if left_t <= time <= right_t:
            weight = (time - left_t) / (right_t - left_t)
            return math.exp(
                (1.0 - weight) * math.log(left_df)
                + weight * math.log(right_df)
            )
    raise RuntimeError("discount-factor interpolation failed")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def bootstrap_zero_coupon(
    quotes: list[dict[str, str]],
    valuation_date: date,
    rate_field: str,
) -> list[Pillar]:
    output: list[Pillar] = []
    for quote in quotes:
        maturity = parse_date(quote["maturity_date"])
        rate = float(quote[rate_field])
        accrual = act_360(valuation_date, maturity)
        discount_factor = 1.0 / (1.0 + rate * accrual)
        output.append(
            Pillar(
                time=act_36525(valuation_date, maturity),
                discount_factor=discount_factor,
                maturity=maturity,
                tenor=quote["tenor_label"],
            )
        )
    return sorted(output, key=lambda item: item.time)


def fixed_annuity(
    effective: date,
    maturity: date,
    discount_curve: Curve,
) -> float:
    result = 0.0
    previous = effective
    for payment in schedule(effective, maturity, 6):
        result += thirty_360(previous, payment) * discount_curve.df(payment)
        previous = payment
    return result


def floating_pv(
    effective: date,
    maturity: date,
    discount_curve: Curve,
    projection_pairs: list[tuple[float, float]],
) -> float:
    result = 0.0
    previous = effective
    for payment in schedule(effective, maturity, 3):
        accrual = act_360(previous, payment)
        previous_time = act_36525(discount_curve.valuation_date, previous)
        payment_time = act_36525(discount_curve.valuation_date, payment)
        previous_df = interpolate_df(projection_pairs, previous_time)
        payment_df = interpolate_df(projection_pairs, payment_time)
        forward = (previous_df / payment_df - 1.0) / accrual
        result += accrual * forward * discount_curve.df(payment)
        previous = payment
    return result


def par_swap_rate(
    effective: date,
    maturity: date,
    discount_curve: Curve,
    projection_pairs: list[tuple[float, float]],
) -> float:
    annuity = fixed_annuity(effective, maturity, discount_curve)
    if annuity <= 0.0:
        raise ValueError("non-positive fixed annuity")
    return floating_pv(
        effective, maturity, discount_curve, projection_pairs
    ) / annuity


def solve_bracket(function) -> float:
    grid = [10.0 ** (-6.0 + index * 6.5 / 200.0) for index in range(201)]
    # Extend above one to permit negative implied zero rates if inputs require it.
    grid.extend([1.0 + index * 0.01 for index in range(1, 101)])
    grid = sorted(set(grid))
    previous_x = grid[0]
    previous_y = function(previous_x)
    for current_x in grid[1:]:
        current_y = function(current_x)
        if previous_y == 0.0:
            return previous_x
        if previous_y * current_y < 0.0:
            return float(
                brentq(
                    function,
                    previous_x,
                    current_x,
                    xtol=1e-14,
                    rtol=1e-14,
                    maxiter=500,
                )
            )
        previous_x, previous_y = current_x, current_y
    raise ValueError("unable to bracket projection discount factor")


def bootstrap_libor(
    deposits: list[dict[str, str]],
    swaps: list[dict[str, str]],
    valuation_date: date,
    spot_date: date,
    ois_curve: Curve,
) -> Curve:
    pillars = bootstrap_zero_coupon(deposits, valuation_date, "rate")
    for quote in sorted(swaps, key=lambda item: parse_date(item["maturity_date"])):
        maturity = parse_date(quote["maturity_date"])
        target_rate = float(quote["par_rate"])
        target_time = act_36525(valuation_date, maturity)

        def residual(trial_df: float) -> float:
            pairs = [(item.time, item.discount_factor) for item in pillars]
            pairs.append((target_time, trial_df))
            pairs.sort()
            return (
                par_swap_rate(spot_date, maturity, ois_curve, pairs)
                - target_rate
            )

        discount_factor = solve_bracket(residual)
        pillars.append(
            Pillar(
                time=target_time,
                discount_factor=discount_factor,
                maturity=maturity,
                tenor=quote["tenor_label"],
            )
        )
        pillars.sort(key=lambda item: item.time)
    return Curve(valuation_date, pillars)


def reprice(
    ois_quotes: list[dict[str, str]],
    deposits: list[dict[str, str]],
    swaps: list[dict[str, str]],
    valuation_date: date,
    spot_date: date,
    ois_curve: Curve,
    libor_curve: Curve,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for quote in ois_quotes:
        maturity = parse_date(quote["maturity_date"])
        input_rate = float(quote["par_rate"])
        model_rate = (1.0 / ois_curve.df(maturity) - 1.0) / act_360(
            valuation_date, maturity
        )
        rows.append(
            {
                "instrument_type": "ois",
                "tenor_label": quote["tenor_label"],
                "input_par_rate": input_rate,
                "model_par_rate": model_rate,
                "residual_bps": (model_rate - input_rate) * 1e4,
            }
        )
    for quote in deposits:
        maturity = parse_date(quote["maturity_date"])
        input_rate = float(quote["rate"])
        model_rate = (1.0 / libor_curve.df(maturity) - 1.0) / act_360(
            valuation_date, maturity
        )
        rows.append(
            {
                "instrument_type": "deposit",
                "tenor_label": quote["tenor_label"],
                "input_par_rate": input_rate,
                "model_par_rate": model_rate,
                "residual_bps": (model_rate - input_rate) * 1e4,
            }
        )
    for quote in swaps:
        maturity = parse_date(quote["maturity_date"])
        input_rate = float(quote["par_rate"])
        model_rate = par_swap_rate(
            spot_date, maturity, ois_curve, libor_curve.pairs()
        )
        rows.append(
            {
                "instrument_type": "irs_3m",
                "tenor_label": quote["tenor_label"],
                "input_par_rate": input_rate,
                "model_par_rate": model_rate,
                "residual_bps": (model_rate - input_rate) * 1e4,
            }
        )
    return rows


def swap_value(
    spec: dict[str, object],
    ois_curve: Curve,
    libor_pairs: list[tuple[float, float]],
) -> dict[str, float | str]:
    effective = parse_date(str(spec["effective_date"]))
    maturity = parse_date(str(spec["maturity_date"]))
    notional = float(spec["notional"])
    fixed_rate = float(spec["fixed_rate"])
    fixed_pv = notional * fixed_rate * fixed_annuity(
        effective, maturity, ois_curve
    )
    float_pv = notional * floating_pv(
        effective, maturity, ois_curve, libor_pairs
    )
    direction = str(spec["pay_receive"])
    if direction == "pay_fixed":
        npv = float_pv - fixed_pv
    elif direction == "receive_fixed":
        npv = fixed_pv - float_pv
    else:
        raise ValueError(f"unknown pay_receive: {direction}")
    return {
        "npv": npv,
        "fixed_leg_pv": fixed_pv,
        "float_leg_pv": float_pv,
        "pay_receive": direction,
    }


def write_curve(path: Path, curve: Curve, libor: bool) -> None:
    if libor:
        columns = [
            "pillar_date",
            "time_years",
            "libor_discount_factor",
            "zero_rate_continuous",
            "forward_3m",
        ]
    else:
        columns = [
            "pillar_date",
            "time_years",
            "discount_factor",
            "zero_rate_continuous",
        ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for pillar in curve.pillars:
            zero = -math.log(pillar.discount_factor) / pillar.time
            row: dict[str, object] = {
                "pillar_date": pillar.maturity.isoformat(),
                "time_years": format(pillar.time, ".17g"),
                "zero_rate_continuous": format(zero, ".17g"),
            }
            if libor:
                next_date = add_months(pillar.maturity, 3)
                next_df = curve.df(next_date)
                forward = (
                    pillar.discount_factor / next_df - 1.0
                ) / act_360(pillar.maturity, next_date)
                row["libor_discount_factor"] = format(
                    pillar.discount_factor, ".17g"
                )
                row["forward_3m"] = format(forward, ".17g")
            else:
                row["discount_factor"] = format(
                    pillar.discount_factor, ".17g"
                )
            writer.writerow(row)


def main() -> None:
    data = Path(os.environ.get("DATA_DIR", "/app/data"))
    output = Path(os.environ.get("OUTPUT_DIR", "/app/output"))
    output.mkdir(parents=True, exist_ok=True)
    conventions = json.loads(
        (data / "conventions.json").read_text(encoding="utf-8")
    )
    valuation_date = parse_date(conventions["valuation_date"])
    spot_date = add_business_days(
        valuation_date, int(conventions["spot_lag_business_days"])
    )
    ois_quotes = read_csv(data / "ois_quotes.csv")
    deposits = read_csv(data / "deposits.csv")
    swaps = read_csv(data / "irs_3m_quotes.csv")
    swap_spec = json.loads(
        (data / "swap_to_value.json").read_text(encoding="utf-8")
    )

    ois_curve = Curve(
        valuation_date,
        bootstrap_zero_coupon(ois_quotes, valuation_date, "par_rate"),
    )
    libor_curve = bootstrap_libor(
        deposits, swaps, valuation_date, spot_date, ois_curve
    )
    repriced = reprice(
        ois_quotes,
        deposits,
        swaps,
        valuation_date,
        spot_date,
        ois_curve,
        libor_curve,
    )
    write_curve(output / "ois_discount_curve.csv", ois_curve, libor=False)
    write_curve(output / "libor_forward_curve.csv", libor_curve, libor=True)
    with (output / "repriced_quotes.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        columns = [
            "instrument_type",
            "tenor_label",
            "input_par_rate",
            "model_par_rate",
            "residual_bps",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in repriced:
            writer.writerow(
                {
                    **row,
                    "input_par_rate": format(float(row["input_par_rate"]), ".17g"),
                    "model_par_rate": format(float(row["model_par_rate"]), ".17g"),
                    "residual_bps": format(float(row["residual_bps"]), ".17g"),
                }
            )

    base_value = swap_value(swap_spec, ois_curve, libor_curve.pairs())
    bump = float(swap_spec.get("pv01_bump_bps", 1.0)) * 1e-4
    bumped_pairs = [
        (time, discount_factor * math.exp(-bump * time))
        for time, discount_factor in libor_curve.pairs()
    ]
    bumped_value = swap_value(swap_spec, ois_curve, bumped_pairs)
    valuation = {
        **base_value,
        "pv01": abs(float(bumped_value["npv"]) - float(base_value["npv"])),
    }
    (output / "swap_valuation.json").write_text(
        json.dumps(valuation, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    five_year = add_months(valuation_date, 60)
    ten_year = add_months(valuation_date, 120)
    ten_year_quote = next(
        quote for quote in swaps if quote["tenor_label"] == "10Y"
    )
    ten_year_maturity = parse_date(ten_year_quote["maturity_date"])
    summary = {
        "ois_5y_zero_rate_continuous": ois_curve.zero(five_year),
        "ois_10y_zero_rate_continuous": ois_curve.zero(ten_year),
        "libor_5y_zero_rate_continuous": libor_curve.zero(five_year),
        "libor_10y_zero_rate_continuous": libor_curve.zero(ten_year),
        "libor_10y_par_swap_rate": par_swap_rate(
            spot_date, ten_year_maturity, ois_curve, libor_curve.pairs()
        ),
        "max_bootstrap_residual_bps": max(
            abs(float(row["residual_bps"])) for row in repriced
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
