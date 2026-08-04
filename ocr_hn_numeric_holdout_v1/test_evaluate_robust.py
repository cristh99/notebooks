from __future__ import annotations

import unittest

from PIL import Image

from .evaluate_robust import sanitize_numeric_tokens


class RobustEvaluationTests(unittest.TestCase):
    def test_invalid_boxes_are_filtered_and_partial_boxes_are_clipped(self) -> None:
        image = Image.new("RGB", (100, 80), "white")
        tokens = [
            {"text": "1234", "bbox": [10, 10, 30, 30]},
            {"text": "5678", "bbox": [120, 5, 140, 20]},
            {"text": "9012", "bbox": [20, 20, 20, 40]},
            {"text": "3456", "bbox": [-5, 10, 15, 25]},
            {"text": "7890", "bbox": [1, 2, float("nan"), 8]},
        ]
        valid, rejected = sanitize_numeric_tokens(tokens, image)
        self.assertEqual(rejected, 3)
        self.assertEqual([row["text"] for row in valid], ["1234", "3456"])
        self.assertEqual(valid[0]["bbox"], [10, 10, 30, 30])
        self.assertEqual(valid[1]["bbox"], [0, 10, 15, 25])

    def test_fully_outside_and_zero_height_boxes_fail_closed(self) -> None:
        image = Image.new("RGB", (50, 50), "white")
        valid, rejected = sanitize_numeric_tokens(
            [
                {"text": "1111", "bbox": [-20, 5, -1, 20]},
                {"text": "2222", "bbox": [5, 50, 20, 50]},
            ],
            image,
        )
        self.assertEqual(valid, [])
        self.assertEqual(rejected, 2)


if __name__ == "__main__":
    unittest.main()
