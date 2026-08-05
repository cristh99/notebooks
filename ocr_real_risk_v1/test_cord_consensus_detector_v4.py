from __future__ import annotations

import unittest

from .cord_consensus_detector_v4 import (
    _candidate_windows,
    cluster_candidates,
    configuration_grid,
    exact_diagnostic,
    guard_accepts,
    resolve_cluster,
)


class CordConsensusDetectorV4Tests(unittest.TestCase):
    def test_numeric_windows_reconstruct_punctuation_split_token(self) -> None:
        rows = [
            {
                "text": "100",
                "bbox": [10, 10, 40, 30],
                "confidence": 94.0,
                "word_num": 1,
            },
            {
                "text": ",",
                "bbox": [41, 10, 45, 30],
                "confidence": 80.0,
                "word_num": 2,
            },
            {
                "text": "000",
                "bbox": [46, 10, 78, 30],
                "confidence": 93.0,
                "word_num": 3,
            },
        ]
        candidates = _candidate_windows(rows, 7)
        reconstructed = [
            row for row in candidates if row["digits"] == "100000"
        ]
        self.assertEqual(len(reconstructed), 1)
        self.assertEqual(reconstructed[0]["bbox"], [10, 10, 78, 30])
        self.assertEqual(reconstructed[0]["word_count"], 2)

    def test_numeric_window_does_not_cross_alpha_label(self) -> None:
        rows = [
            {
                "text": "12",
                "bbox": [0, 0, 20, 20],
                "confidence": 90.0,
                "word_num": 1,
            },
            {
                "text": "TOTAL",
                "bbox": [22, 0, 70, 20],
                "confidence": 90.0,
                "word_num": 2,
            },
            {
                "text": "34",
                "bbox": [72, 0, 92, 20],
                "confidence": 90.0,
                "word_num": 3,
            },
        ]
        candidates = _candidate_windows(rows, 3)
        self.assertNotIn("1234", {row["digits"] for row in candidates})

    def test_cluster_votes_count_distinct_psms_only(self) -> None:
        candidates = [
            {
                "psm": 3,
                "text": "12,345",
                "digits": "12345",
                "bbox": [10, 10, 80, 30],
                "confidence": 90.0,
                "word_count": 1,
            },
            {
                "psm": 3,
                "text": "12345",
                "digits": "12345",
                "bbox": [11, 10, 80, 30],
                "confidence": 95.0,
                "word_count": 1,
            },
            {
                "psm": 6,
                "text": "12.345",
                "digits": "12345",
                "bbox": [9, 9, 81, 31],
                "confidence": 92.0,
                "word_count": 1,
            },
        ]
        clusters = cluster_candidates(candidates)
        self.assertEqual(len(clusters), 1)
        config = {
            "psms": [3, 6, 11],
            "minimum_distinct_psm_votes": 2,
            "reject_equal_length_conflict": False,
        }
        resolved = resolve_cluster(clusters[0], config)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["digits"], "12345")
        self.assertEqual(resolved["distinct_psm_votes"], 2)
        self.assertEqual(resolved["voting_psms"], [3, 6])

    def test_equal_length_conflict_can_fail_closed(self) -> None:
        candidates = [
            {
                "psm": 3,
                "text": "6400",
                "digits": "6400",
                "bbox": [10, 10, 60, 30],
                "confidence": 90.0,
                "word_count": 1,
            },
            {
                "psm": 6,
                "text": "8400",
                "digits": "8400",
                "bbox": [10, 10, 60, 30],
                "confidence": 95.0,
                "word_count": 1,
            },
        ]
        cluster = cluster_candidates(candidates)[0]
        permissive = resolve_cluster(
            cluster,
            {
                "psms": [3, 6],
                "minimum_distinct_psm_votes": 1,
                "reject_equal_length_conflict": False,
            },
        )
        strict = resolve_cluster(
            cluster,
            {
                "psms": [3, 6],
                "minimum_distinct_psm_votes": 1,
                "reject_equal_length_conflict": True,
            },
        )
        self.assertIsNotNone(permissive)
        self.assertIsNone(strict)

    def test_guard_modes_are_explicit(self) -> None:
        guard = {
            "readings": {
                "gray": {"digits": "6400"},
                "autocontrast": {"digits": ""},
            }
        }
        self.assertTrue(guard_accepts(guard, "8400", "none"))
        self.assertTrue(guard_accepts(guard, "6400", "psm7_any"))
        self.assertFalse(guard_accepts(guard, "6400", "psm7_both"))
        self.assertFalse(guard_accepts(guard, "8400", "psm7_any"))

    def test_configuration_grid_is_complete_and_unique(self) -> None:
        configurations = configuration_grid()
        self.assertEqual(len(configurations), 48)
        self.assertEqual(
            len({row["id"] for row in configurations}),
            len(configurations),
        )
        self.assertTrue(
            all(
                row["uses_truth_for_candidate_construction"] is False
                and row[
                    "uses_annotation_bbox_for_candidate_construction"
                ]
                is False
                for row in configurations
            )
        )

    def test_exact_diagnostic_needs_coverage_and_zero_retained_error(self) -> None:
        passing = exact_diagnostic(
            {
                "selected": 800,
                "eligible": 500,
                "baseline_errors": 100,
                "final_accepted": 300,
                "natural_false_accepts": 0,
                "counterfactual_false_accepts": 0,
            }
        )
        self.assertTrue(passing["development_gate"])
        self.assertGreaterEqual(passing["reduction_lower"], 10.0)
        low_coverage = exact_diagnostic(
            {
                "selected": 800,
                "eligible": 500,
                "baseline_errors": 100,
                "final_accepted": 100,
                "natural_false_accepts": 0,
                "counterfactual_false_accepts": 0,
            }
        )
        self.assertFalse(low_coverage["development_gate"])
        retained_error = exact_diagnostic(
            {
                "selected": 800,
                "eligible": 500,
                "baseline_errors": 100,
                "final_accepted": 300,
                "natural_false_accepts": 1,
                "counterfactual_false_accepts": 0,
            }
        )
        self.assertFalse(retained_error["development_gate"])


if __name__ == "__main__":
    unittest.main()
