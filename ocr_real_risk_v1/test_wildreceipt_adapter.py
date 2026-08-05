from __future__ import annotations

import copy
import unittest

from .wildreceipt_adapter import (
    BBOX_COORDINATE_SPACE,
    DATASET_REVISION,
    annotation_bbox,
    canonical_ascii_numeric_word,
    physical_evidence_key,
    select_numeric_annotation,
)


class WildReceiptAdapterTests(unittest.TestCase):
    def test_ascii_numeric_scope_is_explicit(self) -> None:
        self.assertEqual(canonical_ascii_numeric_word("$ 12,345.67"), "1234567")
        self.assertEqual(canonical_ascii_numeric_word("12 34"), "1234")
        self.assertIsNone(canonical_ascii_numeric_word("٢٠٢٤"))
        self.assertIsNone(canonical_ascii_numeric_word("2024"))
        self.assertIsNone(canonical_ascii_numeric_word("1111"))
        self.assertIsNone(canonical_ascii_numeric_word("AB12,345"))
        self.assertIsNone(canonical_ascii_numeric_word("123"))
        self.assertIsNone(canonical_ascii_numeric_word("1234567890123"))

    def test_bbox_projects_layoutlm_xyxy_and_polygon_into_pixels(self) -> None:
        self.assertEqual(
            annotation_bbox([100, 200, 550, 800], (200, 100)),
            ((20, 20, 110, 80), False),
        )
        self.assertEqual(
            annotation_bbox(
                [100, 200, 550, 200, 550, 800, 100, 800],
                (200, 100),
            ),
            ((20, 20, 110, 80), False),
        )
        self.assertEqual(
            annotation_bbox([-20, 200, 1020, 800], (200, 100)),
            ((0, 20, 200, 80), True),
        )
        self.assertEqual(
            annotation_bbox([0, 0, 1, 1], (20, 30)),
            ((0, 0, 1, 1), False),
        )
        with self.assertRaisesRegex(RuntimeError, "no overlap"):
            annotation_bbox([1100, 200, 1200, 800], (200, 100))
        with self.assertRaisesRegex(RuntimeError, "non-positive area"):
            annotation_bbox([500, 500, 400, 600], (200, 100))
        with self.assertRaisesRegex(RuntimeError, "4 or 8"):
            annotation_bbox([1, 2, 3], (200, 100))

    def test_selection_is_order_independent_after_projection(self) -> None:
        base = {
            "image": {"bytes": b"unused"},
            "id": 7,
            "words": ["12,345", "TOTAL", "67.890"],
            "bboxes": [
                [10, 10, 200, 100],
                [10, 120, 400, 220],
                [10, 240, 200, 340],
            ],
        }
        first, first_counts = select_numeric_annotation(
            row=base,
            shard_id="train-0",
            image_sha256="a" * 64,
            image_size=(100, 100),
        )
        reordered = copy.deepcopy(base)
        reordered["words"] = [base["words"][2], base["words"][1], base["words"][0]]
        reordered["bboxes"] = [base["bboxes"][2], base["bboxes"][1], base["bboxes"][0]]
        second, second_counts = select_numeric_annotation(
            row=reordered,
            shard_id="train-0",
            image_sha256="a" * 64,
            image_size=(100, 100),
        )
        self.assertEqual(first["truth"], second["truth"])
        self.assertEqual(first["bbox"], second["bbox"])
        self.assertEqual(
            first["selection_rank_sha256"], second["selection_rank_sha256"]
        )
        self.assertEqual(first["bbox_coordinate_space"], "image_pixels")
        self.assertEqual(
            first["source_bbox_coordinate_space"], BBOX_COORDINATE_SPACE
        )
        self.assertEqual(first_counts["unique_numeric_candidates"], 2)
        self.assertEqual(second_counts["unique_numeric_candidates"], 2)
        self.assertEqual(
            first_counts["numeric_annotations_projected_to_pixels"], 2
        )

    def test_selection_deduplicates_same_physical_annotation(self) -> None:
        row = {
            "image": {"bytes": b"unused"},
            "id": "receipt-a",
            "words": ["12,345", "12345"],
            "bboxes": [[10, 10, 200, 100], [10, 10, 200, 100]],
        }
        selected, counts = select_numeric_annotation(
            row=row,
            shard_id="test",
            image_sha256="b" * 64,
            image_size=(100, 100),
        )
        self.assertEqual(selected["truth"], "12345")
        self.assertEqual(selected["bbox"], [1, 1, 20, 10])
        self.assertEqual(counts["numeric_annotations_in_scope"], 2)
        self.assertEqual(counts["unique_numeric_candidates"], 1)

    def test_missing_or_misaligned_fields_fail_closed(self) -> None:
        base = {
            "image": {"bytes": b"unused"},
            "id": 1,
            "words": ["12345"],
            "bboxes": [[10, 10, 200, 100]],
        }
        broken = dict(base)
        broken.pop("words")
        with self.assertRaisesRegex(RuntimeError, "missing words"):
            select_numeric_annotation(
                row=broken,
                shard_id="test",
                image_sha256="c" * 64,
                image_size=(100, 100),
            )
        broken = dict(base)
        broken["bboxes"] = []
        with self.assertRaisesRegex(RuntimeError, "length mismatch"):
            select_numeric_annotation(
                row=broken,
                shard_id="test",
                image_sha256="c" * 64,
                image_size=(100, 100),
            )

    def test_physical_identity_is_stable(self) -> None:
        first = physical_evidence_key("f" * 64, [1, 2, 3, 4])
        second = physical_evidence_key("f" * 64, (1, 2, 3, 4))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertEqual(len(DATASET_REVISION), 40)
        self.assertEqual(BBOX_COORDINATE_SPACE, "layoutlm_normalized_xyxy_0_1000")


if __name__ == "__main__":
    unittest.main()
