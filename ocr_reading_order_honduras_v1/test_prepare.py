from __future__ import annotations

import unittest

from .prepare_holdout import group_tesseract_blocks, ordered_ids


class HonduranPreparationTests(unittest.TestCase):
    def test_group_words_into_blocks(self) -> None:
        data = {
            "text": ["Uno", "dos", "", "Tres"],
            "block_num": [1, 1, 1, 2],
            "left": [0, 20, 0, 60],
            "top": [0, 0, 0, 20],
            "width": [15, 15, 0, 20],
            "height": [10, 10, 0, 10],
            "conf": [90, 80, -1, 70],
        }
        blocks = group_tesseract_blocks(data)
        self.assertEqual([item["block_id"] for item in blocks], ["B000", "B001"])
        self.assertEqual(blocks[0]["text"], "Uno dos")
        self.assertEqual(blocks[0]["bbox"], [0.0, 0.0, 35.0, 10.0])

    def test_frozen_xycut_changes_column_interleaving(self) -> None:
        blocks = [
            {"block_id": "B000", "bbox": [0, 0, 40, 10]},
            {"block_id": "B001", "bbox": [60, 0, 100, 10]},
            {"block_id": "B002", "bbox": [0, 20, 40, 30]},
            {"block_id": "B003", "bbox": [60, 20, 100, 30]},
        ]
        baseline = ordered_ids(blocks, 100, 100, "yx_baseline")
        geometry = ordered_ids(blocks, 100, 100, "xycut_loose")
        self.assertEqual(baseline, ["B000", "B001", "B002", "B003"])
        self.assertEqual(geometry, ["B000", "B002", "B001", "B003"])

    def test_order_is_permutation(self) -> None:
        blocks = [
            {"block_id": "B000", "bbox": [0, 0, 40, 10]},
            {"block_id": "B001", "bbox": [0, 20, 40, 30]},
        ]
        order = ordered_ids(blocks, 100, 100, "xycut_loose")
        self.assertEqual(set(order), {"B000", "B001"})
        self.assertEqual(len(order), 2)


if __name__ == "__main__":
    unittest.main()
