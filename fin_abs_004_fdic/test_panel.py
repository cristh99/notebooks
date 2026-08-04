from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from .panel import (
    FEATURE_COLUMNS,
    MONOTONIC_DIRECTIONS,
    WINDOWS,
    add_features,
    add_labels,
    assign_split,
    quarter_ends,
)


class FdicPanelTests(unittest.TestCase):
    def test_quarter_ends_are_exact(self) -> None:
        dates = quarter_ends(pd.Timestamp("2009-03-31"), pd.Timestamp("2009-12-31"))
        self.assertEqual(
            [value.date().isoformat() for value in dates],
            ["2009-03-31", "2009-06-30", "2009-09-30", "2009-12-31"],
        )

    def test_split_windows_are_nonoverlapping(self) -> None:
        dates = pd.Series(
            pd.to_datetime(
                ["2002-12-31", "2003-03-31", "2005-03-31", "2009-03-31"]
            )
        )
        self.assertEqual(
            assign_split(dates).tolist(),
            ["train", "gap", "validation", "test"],
        )
        windows = list(WINDOWS.values())
        for index, (start, end) in enumerate(windows):
            for other_start, other_end in windows[index + 1 :]:
                self.assertTrue(end < other_start or other_end < start)

    def test_assistance_is_not_labeled_as_failure(self) -> None:
        panel = pd.DataFrame(
            {
                "CERT": [1, 2],
                "REPDTE": pd.to_datetime(["2000-12-31", "2000-12-31"]),
            }
        )
        failures = pd.DataFrame(
            {
                "CERT": [1, 2],
                "FAILDATE": ["02/01/2001", "02/01/2001"],
                "RESTYPE": ["ASSISTANCE", "FAILURE"],
            }
        )
        labeled, report = add_labels(panel, failures)
        self.assertEqual(labeled["label"].tolist(), [0, 1])
        self.assertEqual(labeled["assistance_within_horizon"].tolist(), [1, 0])
        self.assertEqual(report["assistance_records_excluded"], 1)

    def test_feature_growth_requires_four_quarter_gap(self) -> None:
        rows = []
        for index, date in enumerate(
            pd.to_datetime(
                ["2000-03-31", "2000-06-30", "2000-09-30", "2000-12-31", "2001-03-31"]
            )
        ):
            rows.append(
                {
                    "CERT": 1,
                    "REPDTE": date,
                    "ASSET": 100.0 + 10 * index,
                    "EQ": 10.0,
                    "DEP": 80.0,
                    "LNLSNET": 60.0,
                    "NETINC": 1.0,
                    "ROA": 1.0,
                    "ROE": 10.0,
                    "NCLNLSR": 2.0,
                    "NPERFV": 2.0,
                    "NTLNLSR": 2.0,
                    "NTRERESR": 0.5,
                    "NIM": 3.0,
                    "RBC1AAJ": np.nan,
                    "RBCRWAJ": np.nan,
                    "IDT1CER": np.nan,
                    "IDT1RWAJR": np.nan,
                    "LNATRESR": 1.0,
                    "COREDEP": 70.0,
                    "DEPUNINS": 10.0,
                    "FREPO": 5.0,
                    "SC": 20.0,
                    "ACTIVE": 1,
                }
            )
        featured = add_features(pd.DataFrame(rows))
        self.assertTrue(pd.isna(featured.loc[3, "asset_growth_yoy"]))
        self.assertAlmostEqual(
            float(featured.loc[4, "asset_growth_yoy"]),
            140.0 / 100.0 - 1.0,
        )

    def test_feature_and_monotonic_contracts_align(self) -> None:
        self.assertEqual(set(FEATURE_COLUMNS), set(MONOTONIC_DIRECTIONS))
        self.assertTrue(all(value in {-1, 0, 1} for value in MONOTONIC_DIRECTIONS.values()))


if __name__ == "__main__":
    unittest.main()
