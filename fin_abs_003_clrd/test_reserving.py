from __future__ import annotations

import unittest

import pandas as pd

from .reserving import method_metrics, paired_entity_bootstrap, select_method
from .reserving_v2 import prior_elr_by_lob, temporal_information_contract


class ClrdReservingTests(unittest.TestCase):
    def test_prior_elr_excludes_future_cells_and_nontrain_entities(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "GRCODE": "1",
                    "LOB": "wkcomp",
                    "AccidentYear": 1994,
                    "DevelopmentYear": 1994,
                    "IncurLoss": 100.0,
                    "EarnedPremNet": 200.0,
                    "split": "train",
                },
                {
                    "GRCODE": "1",
                    "LOB": "wkcomp",
                    "AccidentYear": 1994,
                    "DevelopmentYear": 1997,
                    "IncurLoss": 10000.0,
                    "EarnedPremNet": 200.0,
                    "split": "train",
                },
                {
                    "GRCODE": "2",
                    "LOB": "wkcomp",
                    "AccidentYear": 1994,
                    "DevelopmentYear": 1994,
                    "IncurLoss": 9000.0,
                    "EarnedPremNet": 100.0,
                    "split": "test",
                },
            ]
        )
        result = prior_elr_by_lob(frame, 1994)
        self.assertAlmostEqual(result["wkcomp"], 0.5)

    def test_temporal_contract_is_fail_closed(self) -> None:
        rows = []
        for split, grcode in (("train", "1"), ("validation", "2"), ("test", "3")):
            for year in (1994, 1995, 1996):
                rows.append(
                    {
                        "GRCODE": grcode,
                        "split": split,
                        "DevelopmentYear": year,
                    }
                )
        contract = temporal_information_contract(pd.DataFrame(rows))
        self.assertTrue(contract["entity_sets_disjoint"])
        self.assertTrue(contract["all_cutoffs_no_future"])
        self.assertEqual(contract["cutoffs"]["1994"]["visible_max_development_year"], 1994)

    def test_method_metrics_are_exact_on_simple_case(self) -> None:
        frame = pd.DataFrame(
            {
                "actual_reserve": [100.0, 200.0],
                "prediction": [90.0, 220.0],
                "LOB": ["a", "b"],
                "cutoff": [1994, 1995],
            }
        )
        metrics = method_metrics(frame)
        self.assertAlmostEqual(metrics["wape"], 30.0 / 300.0)
        self.assertAlmostEqual(metrics["calibration_ratio"], 310.0 / 300.0)
        self.assertEqual(metrics["cases"], 2)

    def test_validation_selection_prefers_lowest_wape(self) -> None:
        metrics = {
            "A": {"wape": 0.2, "calibration_error": 0.01, "p95_ape": 0.5},
            "B": {"wape": 0.1, "calibration_error": 0.03, "p95_ape": 0.8},
        }
        self.assertEqual(select_method(metrics, ("A", "B")), "B")

    def test_entity_bootstrap_is_deterministic(self) -> None:
        rows = []
        for entity, actual, baseline, challenger in (
            ("1", 100.0, 150.0, 110.0),
            ("2", 200.0, 100.0, 190.0),
            ("3", 300.0, 450.0, 320.0),
        ):
            case_id = f"case-{entity}"
            for method, prediction in (("BASE", baseline), ("CHALL", challenger)):
                rows.append(
                    {
                        "GRCODE": entity,
                        "case_id": case_id,
                        "method": method,
                        "actual_reserve": actual,
                        "prediction": prediction,
                    }
                )
        frame = pd.DataFrame(rows)
        first = paired_entity_bootstrap(frame, "BASE", "CHALL", replicates=100)
        second = paired_entity_bootstrap(frame, "BASE", "CHALL", replicates=100)
        self.assertEqual(first, second)
        self.assertGreater(first["mean_improvement"], 0)


if __name__ == "__main__":
    unittest.main()
