from __future__ import annotations

import unittest

from .run_canary import (
    GTBlock,
    GTPage,
    OCRLine,
    match_lines,
    reorder,
    sequence_metrics,
    text_metrics,
)


class TesseractOrderTests(unittest.TestCase):
    def test_frozen_xycut_repairs_two_columns(self) -> None:
        lines = [
            OCRLine("l1", "left one", (0, 0, 40, 10), 0.9),
            OCRLine("r1", "right one", (60, 0, 100, 10), 0.9),
            OCRLine("l2", "left two", (0, 20, 40, 30), 0.9),
            OCRLine("r2", "right two", (60, 20, 100, 30), 0.9),
        ]
        baseline, _ = reorder(lines, "yx_baseline")
        geometry, _ = reorder(lines, "xycut_loose")
        self.assertEqual([line.line_id for line in baseline], ["l1", "r1", "l2", "r2"])
        self.assertEqual([line.line_id for line in geometry], ["l1", "l2", "r1", "r2"])

    def test_match_and_sequence_metrics(self) -> None:
        page = GTPage(
            "p", 100, 100, "double_column", "book", "english",
            (
                GTBlock("g1", 0, "a", (0, 0, 40, 40)),
                GTBlock("g2", 1, "b", (60, 0, 100, 40)),
            ),
        )
        lines = [
            OCRLine("l1", "a", (1, 1, 39, 10), 0.9),
            OCRLine("l2", "b", (61, 1, 99, 10), 0.9),
        ]
        matches = match_lines(lines, page.blocks)
        self.assertEqual(matches, {"l1": "g1", "l2": "g2"})
        metrics = sequence_metrics(page, lines, matches)
        self.assertEqual(metrics["conditional_read_order_edit"], 0.0)
        self.assertEqual(metrics["match_coverage"], 1.0)

    def test_text_metrics_exact(self) -> None:
        metrics = text_metrics("alpha beta", "alpha beta")
        self.assertEqual(metrics["character_accuracy"], 1.0)
        self.assertEqual(metrics["word_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
