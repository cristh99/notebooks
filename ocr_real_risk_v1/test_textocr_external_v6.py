from __future__ import annotations

import unittest

from PIL import Image

from .textocr_external_v6 import (
    MACROFOLD_COUNT,
    MINIMUM_ACCEPTED,
    MINIMUM_COVERAGE_LOWER,
    MINIMUM_SELECTED,
    PARTITION_COUNT,
    TARGET_REDUCTION,
    clip_bbox,
    exact_summary,
    macrofold_id,
    partition_id,
)


def selected_record(row_index: int = 7) -> dict:
    return {
        "row_index": row_index,
        "truth": "1234",
        "bbox_xyxy": [1.0, 2.0, 20.0, 10.0],
        "selection_rank_sha256": "a" * 64,
    }


def observation(
    *,
    baseline_correct: bool = True,
    accepted: bool = False,
    false_accept: bool = False,
    counterfactual_accepted: bool = False,
) -> dict:
    return {
        "baseline": {
            "eligible": True,
            "claim_correct": baseline_correct,
        },
        "candidate": {
            "accepted": accepted,
            "false_accept": false_accept,
        },
        "counterfactual": {
            "accepted": counterfactual_accepted,
        },
    }


class TextOcrExternalV6Tests(unittest.TestCase):
    def test_partition_and_macrofold_are_deterministic_and_bounded(self) -> None:
        record = selected_record()
        first = partition_id(record)
        second = partition_id(dict(record))
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, PARTITION_COUNT)
        macro = macrofold_id(record)
        self.assertEqual(macro, first % MACROFOLD_COUNT)
        self.assertGreaterEqual(macro, 0)
        self.assertLess(macro, MACROFOLD_COUNT)

    def test_partition_changes_with_physical_risk_unit(self) -> None:
        first = selected_record(7)
        second = selected_record(8)
        # They may collide modulo 12, but their full deterministic inputs differ.
        self.assertNotEqual(first["row_index"], second["row_index"])
        self.assertIsInstance(partition_id(first), int)
        self.assertIsInstance(partition_id(second), int)

    def test_clip_bbox_clips_edges_and_fails_without_overlap(self) -> None:
        image = Image.new("RGB", (100, 80), "white")
        self.assertEqual(
            clip_bbox([-2, 3, 103, 90], image),
            (0, 3, 100, 80),
        )
        self.assertEqual(clip_bbox([1, 2, 20, 10], image), (1, 2, 20, 10))
        with self.assertRaisesRegex(RuntimeError, "no image overlap"):
            clip_bbox([101, 1, 110, 10], image)
        with self.assertRaisesRegex(RuntimeError, "four coordinates"):
            clip_bbox([1, 2, 3], image)

    def test_exact_gate_can_pass_with_zero_retained_errors(self) -> None:
        rows = []
        for index in range(MINIMUM_SELECTED):
            rows.append(
                observation(
                    baseline_correct=index >= 600,
                    accepted=600 <= index < 1600,
                )
            )
        result = exact_summary(rows)
        self.assertEqual(result["selected"], MINIMUM_SELECTED)
        self.assertEqual(result["baseline_false"], 600)
        self.assertEqual(result["accepted"], 1000)
        self.assertEqual(result["accepted_false"], 0)
        self.assertEqual(result["counterfactual_false"], 0)
        self.assertGreaterEqual(result["accepted"], MINIMUM_ACCEPTED)
        self.assertGreaterEqual(
            result["coverage_lower"], MINIMUM_COVERAGE_LOWER
        )
        self.assertGreaterEqual(result["reduction_lower"], TARGET_REDUCTION)
        self.assertTrue(result["pass"])

    def test_exact_gate_fails_for_risk_coverage_and_counterfactuals(self) -> None:
        low_coverage = [
            observation(
                baseline_correct=index >= 600,
                accepted=600 <= index < 1200,
            )
            for index in range(MINIMUM_SELECTED)
        ]
        self.assertFalse(exact_summary(low_coverage)["pass"])

        unsafe = [
            observation(
                baseline_correct=index >= 600,
                accepted=600 <= index < 1600,
                false_accept=1580 <= index < 1600,
            )
            for index in range(MINIMUM_SELECTED)
        ]
        self.assertEqual(exact_summary(unsafe)["accepted_false"], 20)
        self.assertFalse(exact_summary(unsafe)["pass"])

        counterfactual = [
            observation(
                baseline_correct=index >= 600,
                accepted=600 <= index < 1600,
                counterfactual_accepted=index < 80,
            )
            for index in range(MINIMUM_SELECTED)
        ]
        result = exact_summary(counterfactual)
        self.assertEqual(result["counterfactual_false"], 80)
        self.assertGreater(result["counterfactual_upper"], 0.01)
        self.assertFalse(result["pass"])

    def test_underpowered_population_fails_closed(self) -> None:
        rows = [
            observation(
                baseline_correct=index >= 200,
                accepted=200 <= index < 1000,
            )
            for index in range(2000)
        ]
        result = exact_summary(rows)
        self.assertEqual(result["selected"], 2000)
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
