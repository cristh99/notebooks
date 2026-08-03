from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from .audit import (
    asset_class,
    asset_prefix,
    expected_split,
    return_convention_audit,
    split_audit,
)


class PortBenchAuditTests(unittest.TestCase):
    def test_asset_parser_preserves_real_estate_class(self) -> None:
        column = "real_estate_yahoo_VNQ_return"
        prefix = asset_prefix(column)
        self.assertEqual(prefix, "real_estate_yahoo_VNQ")
        self.assertEqual(asset_class(prefix), "real_estate")
        self.assertEqual(asset_class("equities_yahoo_SPY"), "equities")

    def test_pinned_date_split(self) -> None:
        dates = pd.Series(
            pd.to_datetime(
                ["2022-12-30", "2023-01-03", "2024-01-02", "2025-12-31"]
            )
        )
        self.assertEqual(
            expected_split(dates).tolist(),
            ["train", "val", "test", "test"],
        )

    def test_embedded_split_mismatch_is_visible(self) -> None:
        dates = pd.Series(pd.to_datetime(["2022-12-30", "2023-01-03"]))
        frame = pd.DataFrame({"split": ["train", "test"]})
        result = split_audit(frame, dates)
        self.assertFalse(result["embedded_labels_consistent"])
        self.assertEqual(result["details"][0]["mismatches"], 1)

    def test_log_return_convention_is_detected(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=400)
        simple = 0.001 + 0.0002 * np.sin(np.arange(len(dates)))
        close = 100.0 * np.cumprod(1.0 + simple)
        log_return = np.log(pd.Series(close) / pd.Series(close).shift(1))
        frame = pd.DataFrame(
            {
                "date": dates,
                "equities_yahoo_SYN_close": close,
                "equities_yahoo_SYN_return": log_return,
            }
        )
        result = return_convention_audit(
            frame,
            ["equities_yahoo_SYN_return"],
        )
        self.assertEqual(result["inferred_convention"], "log_return")
        self.assertLess(
            result["median_abs_error_log"],
            result["median_abs_error_simple"],
        )


if __name__ == "__main__":
    unittest.main()
