from __future__ import annotations

import math
import unittest
from datetime import date

import numpy as np
import pandas as pd

from .bs_greeks_pde import point
from .double_sort import deterministic_bucket
from .kelly_var_sizing import parametric_var
from .structured_note_risk import down_and_out_call, option_delta
from .swap_curve_bootstrap_ois import act_360, interpolate_df, schedule, thirty_360


class SolutionContractTests(unittest.TestCase):
    def test_black_scholes_pde_and_parity(self) -> None:
        values = point(100.0, 100.0, 0.5, 0.20)
        self.assertLess(abs(values["call_pde_residual"]), 1e-10)
        self.assertLess(abs(values["put_pde_residual"]), 1e-10)
        self.assertLess(values["parity_error"], 1e-12)
        self.assertGreater(values["gamma"], 0.0)
        self.assertGreater(values["vega"], 0.0)

    def test_deterministic_quintiles(self) -> None:
        values = pd.Series([9.0, 1.0, 3.0, 7.0, 5.0, 2.0, 4.0, 8.0, 6.0, 0.0])
        identifiers = pd.Series(range(10))
        buckets = deterministic_bucket(values, identifiers)
        self.assertEqual(sorted(buckets.unique().tolist()), [0, 1, 2, 3, 4])
        self.assertEqual(int(buckets.loc[9]), 0)
        self.assertEqual(int(buckets.loc[0]), 4)

    def test_parametric_var_is_positive(self) -> None:
        fractions = np.array([1.0, 0.5])
        mean_excess = np.array([0.0002, 0.0001])
        covariance = np.array([[0.0001, 0.00002], [0.00002, 0.0002]])
        self.assertGreater(
            parametric_var(fractions, mean_excess, covariance, 0.99),
            0.0,
        )

    def test_barrier_price_and_delta_are_bounded(self) -> None:
        from scipy.stats import norm

        spot = strike = 100.0
        rate = 0.03
        maturity = 1.0
        volatility = 0.20
        d1 = (rate + 0.5 * volatility**2) / volatility
        d2 = d1 - volatility
        vanilla = spot * norm.cdf(d1) - strike * math.exp(-rate) * norm.cdf(d2)
        price = down_and_out_call(
            spot, strike, 70.0, rate, maturity, volatility
        )
        self.assertGreaterEqual(price, 0.0)
        self.assertLessEqual(price, vanilla + 1e-10)
        delta = option_delta(spot, strike, 70.0, rate, maturity, volatility)
        self.assertGreater(delta, 0.0)
        self.assertLess(delta, 1.0)

    def test_curve_and_schedule_contracts(self) -> None:
        pairs = [(1.0, math.exp(-0.03)), (2.0, math.exp(-0.08))]
        self.assertAlmostEqual(interpolate_df(pairs, 1.5), math.exp(-0.055), places=12)
        effective = date(2024, 3, 19)
        maturity = date(2025, 3, 19)
        dates = schedule(effective, maturity, 3)
        self.assertEqual(len(dates), 4)
        self.assertEqual(dates[-1], maturity)
        self.assertGreater(act_360(effective, dates[0]), 0.0)
        self.assertAlmostEqual(thirty_360(effective, date(2024, 9, 19)), 0.5)


if __name__ == "__main__":
    unittest.main()
