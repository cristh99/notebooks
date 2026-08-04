from __future__ import annotations

import unittest

from .evaluate_dual_anchor import filter_words_by_anchor


class DualAnchorEvaluationTests(unittest.TestCase):
    def test_filter_preserves_page_word_count_and_blanks_only_unanchored_numbers(self) -> None:
        words = [
            {"text": "Proyecto", "bbox_pt": [0, 0, 10, 10]},
            {"text": "110509", "bbox_pt": [11, 0, 20, 10]},
            {"text": "999999", "bbox_pt": [21, 0, 30, 10]},
            {"text": "2025", "bbox_pt": [31, 0, 40, 10]},
        ]
        filtered, counts = filter_words_by_anchor(words, {"110509"})
        self.assertEqual(len(filtered), len(words))
        self.assertEqual(filtered[0]["text"], "Proyecto")
        self.assertEqual(filtered[1]["text"], "110509")
        self.assertEqual(filtered[2]["text"], "")
        # Years are already outside the measured PDF truth protocol and remain
        # irrelevant without being counted as an anchor rejection.
        self.assertEqual(filtered[3]["text"], "2025")
        self.assertEqual(counts["anchored_numeric_words"], 1)
        self.assertEqual(counts["unanchored_numeric_words_excluded"], 1)
        self.assertEqual(counts["non_numeric_words_preserved"], 2)

    def test_empty_anchor_set_removes_all_eligible_numeric_truths(self) -> None:
        words = [
            {"text": "108919"},
            {"text": "texto"},
            {"text": "2024"},
        ]
        filtered, counts = filter_words_by_anchor(words, set())
        self.assertEqual([row["text"] for row in filtered], ["", "texto", "2024"])
        self.assertEqual(counts["unanchored_numeric_words_excluded"], 1)


if __name__ == "__main__":
    unittest.main()
