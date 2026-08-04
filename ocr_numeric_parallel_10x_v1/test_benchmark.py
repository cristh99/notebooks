from __future__ import annotations

import unittest
from collections import Counter

from .benchmark import (
    counter_parity,
    evaluate_pages,
    percentile,
    runtime_metrics,
    stable_payload,
)


class ParallelNumericProofTests(unittest.TestCase):
    def test_quality_requires_repeated_independent_intersection(self) -> None:
        pages = [
            {
                "page_id": "p1",
                "reference_tokens": ["1", "1", "2", "2"],
                "tesseract_tokens": ["1", "1", "2", "2", "9", "9"],
                "pp_1024_tokens": ["1", "1", "2", "2"],
                "accepted_tokens": ["1", "1", "2", "2"],
            }
        ]
        result = evaluate_pages(pages)
        self.assertEqual(result["policy"]["precision"], 1.0)
        self.assertEqual(result["policy"]["prediction_count"], 4)

    def test_runtime_metrics_measure_pair_against_tesseract(self) -> None:
        rows = [
            {
                "isolated": {
                    "tesseract": {"runtime": {"wall_seconds": 2.0}},
                    "pp_1024": {"runtime": {"wall_seconds": 0.5}},
                },
                "parallel": {"pair_wall_seconds": 2.1},
            },
            {
                "isolated": {
                    "tesseract": {"runtime": {"wall_seconds": 3.0}},
                    "pp_1024": {"runtime": {"wall_seconds": 0.7}},
                },
                "parallel": {"pair_wall_seconds": 3.1},
            },
        ]
        metrics = runtime_metrics(rows)
        self.assertAlmostEqual(metrics["pair_ratio_to_tesseract"], 5.2 / 5.0)
        self.assertAlmostEqual(
            metrics["mean_extra_wall_seconds_per_page"],
            0.1,
        )
        self.assertGreater(metrics["pp_wall_fraction_hidden"], 0.8)

    def test_counter_parity_is_exact_for_equal_multisets(self) -> None:
        result = counter_parity(
            Counter({"1": 2, "5": 1}),
            Counter({"5": 1, "1": 2}),
        )
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["matching_count"], 3)

    def test_percentile_is_nearest_rank(self) -> None:
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.90), 4.0)
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.50), 2.0)

    def test_stable_payload_excludes_environment_and_digest(self) -> None:
        report = {
            "schema": "x",
            "value": 2,
            "environment": {"host": "runner"},
            "stable_payload_sha256": "bad",
        }
        self.assertEqual(stable_payload(report), {"schema": "x", "value": 2})


if __name__ == "__main__":
    unittest.main()
