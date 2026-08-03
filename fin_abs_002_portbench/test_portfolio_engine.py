from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from .portfolio_engine import (
    MarketData,
    capped_weights,
    moving_block_bootstrap_ci,
    performance_metrics,
    risk_parity_weights,
    run_backtest,
)


class PortBenchEngineTests(unittest.TestCase):
    def test_risk_parity_is_normalized_and_positive(self) -> None:
        cov = np.array([[0.04, 0.01], [0.01, 0.09]], dtype=float)
        weights = risk_parity_weights(cov)
        self.assertAlmostEqual(float(weights.sum()), 1.0, places=10)
        self.assertTrue((weights > 0).all())
        contributions = weights * (cov @ weights)
        self.assertAlmostEqual(float(contributions[0]), float(contributions[1]), places=5)

    def _six_class_universe(self) -> tuple[list[str], dict[str, str]]:
        assets = [
            *(f"equities_SYN_{index}" for index in range(10)),
            *(f"bonds_SYN_{index}" for index in range(10)),
            *(f"commodities_SYN_{index}" for index in range(10)),
            *(f"real_estate_SYN_{index}" for index in range(10)),
            *(f"cryptocurrency_SYN_{index}" for index in range(10)),
            *(f"cash_SYN_{index}" for index in range(10)),
        ]
        class_map = {
            asset: (
                "real_estate"
                if asset.startswith("real_estate_")
                else asset.split("_", 1)[0]
            )
            for asset in assets
        }
        return assets, class_map

    def _assert_caps(
        self,
        weights: np.ndarray,
        assets: list[str],
        class_map: dict[str, str],
    ) -> None:
        self.assertAlmostEqual(float(weights.sum()), 1.0, places=9)
        self.assertLessEqual(float(weights.max()), 0.10000001)
        for name in set(class_map.values()):
            total = sum(
                weights[index]
                for index, asset in enumerate(assets)
                if class_map[asset] == name
            )
            self.assertLessEqual(float(total), 0.35000001)

    def test_caps_are_respected(self) -> None:
        assets, class_map = self._six_class_universe()
        raw = np.linspace(1.0, 3.0, len(assets))
        weights = capped_weights(raw, assets, class_map)
        self._assert_caps(weights, assets, class_map)

    def test_caps_fill_exactly_under_extreme_concentration(self) -> None:
        assets, class_map = self._six_class_universe()
        raw = np.full(len(assets), 1e-15)
        raw[0] = 1.0
        raw[1] = 0.5
        weights = capped_weights(raw, assets, class_map)
        self._assert_caps(weights, assets, class_map)
        equity_total = sum(
            weights[index]
            for index, asset in enumerate(assets)
            if class_map[asset] == "equities"
        )
        self.assertAlmostEqual(float(equity_total), 0.35, places=9)

    def test_bootstrap_is_deterministic(self) -> None:
        differences = [0.01, -0.005, 0.02, 0.004, 0.003, -0.001]
        first = moving_block_bootstrap_ci(differences, replicates=100)
        second = moving_block_bootstrap_ci(differences, replicates=100)
        self.assertEqual(first, second)

    def test_backtest_uses_only_prior_history(self) -> None:
        index = pd.bdate_range("2019-01-01", "2025-12-31")
        rng = np.random.default_rng(42)
        assets = [
            "equities_yahoo_EQ1",
            "equities_yahoo_EQ2",
            "bonds_yahoo_BD1",
            "bonds_yahoo_BD2",
            "commodities_yahoo_CM1",
            "real_estate_yahoo_RE1",
            "cryptocurrency_yahoo_CR1",
            "cash_yahoo_CA1",
        ]
        values = rng.normal(0.0002, 0.005, size=(len(index), len(assets)))
        values[:, -1] = rng.normal(0.00005, 0.0002, size=len(index))
        returns = pd.DataFrame(values, index=index, columns=assets)
        classes = {
            asset: (
                "real_estate"
                if asset.startswith("real_estate_")
                else asset.split("_", 1)[0]
            )
            for asset in assets
        }
        split = pd.Series(
            np.where(index.year <= 2022, "train", np.where(index.year == 2023, "val", "test")),
            index=index,
        )
        market = MarketData(
            returns=returns,
            class_map=classes,
            split=split,
            dataset_sha256="synthetic",
            embedded_split_columns=(),
        )
        result = run_backtest(market, "risk_parity", "2023-01-01", "2023-12-31")
        self.assertEqual(result.pit_violations, 0)
        self.assertEqual(result.metrics["observations"], len(returns.loc["2023"]))
        self.assertAlmostEqual(float(result.weights.sum(axis=1).iloc[-1]), 1.0, places=8)

    def test_performance_metrics_include_costs(self) -> None:
        index = pd.bdate_range("2024-01-01", periods=4)
        daily = pd.DataFrame(
            {
                "gross_return": [0.01, 0.0, -0.01, 0.02],
                "net_return": [0.009, 0.0, -0.01, 0.02],
                "turnover": [1.0, 0.0, 0.0, 0.0],
                "cost": [0.001, 0.0, 0.0, 0.0],
            },
            index=index,
        )
        weights = pd.DataFrame({"asset": [1.0] * 4}, index=index)
        metrics = performance_metrics(daily, weights)
        self.assertEqual(metrics["observations"], 4)
        self.assertAlmostEqual(float(metrics["turnover"]), 1.0)
        self.assertAlmostEqual(float(metrics["total_cost"]), 0.001)


if __name__ == "__main__":
    unittest.main()
