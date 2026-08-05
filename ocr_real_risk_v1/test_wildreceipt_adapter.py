from __future__ import annotations

import copy
import unittest

from .wildreceipt_adapter import (
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

    def test_bbox_accepts_xyxy_and_polygon_and_clips(self) -> None:
        self.assertEqual(annotation_bbox([1, 2, 11, 22], (20, 30)), ((1, 2, 11, 22), False))
        self.assertEqual(
            annotation_bbox([1, 2, 11, 2, 11, 22, 1, 22], (20, 30)),
            ((1, 2, 11, 22), False),
        )
        self.assertEqual(
            annotation_bbox([-2, 2, 21, 31], (20, 30)),
            ((0, 2, 20, 30), True),
        )
        with self.assertRaisesRegex(RuntimeError, "no overlap"):
            annotation_bbox([21, 2, 30, 20], (20, 30))
        with self.assertRaisesRegex(RuntimeError, "4 or 8"):
            annotation_bbox([1, 2, 3], (20, 30))

    def test_selection_is_order_independent(self) -> None:
        base = {
            "image": {"bytes": b"unused"},
            "id": 7,
            "words": ["12,345", "TOTAL", "67.890"],
            "bboxes": [[1, 1, 20, 10], [1, 12, 40, 22], [1, 24, 20, 34]],
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
        self.assertEqual(first_counts["unique_numeric_candidates"], 2)
        self.assertEqual(second_counts["unique_numeric_candidates"], 2)

    def test_selection_deduplicates_same_physical_annotation(self) -> None:
        row = {
            "image": {"bytes": b"unused"},
            "id": "receipt-a",
            "words": ["12,345", "12345"],
            "bboxes": [[1, 1, 20, 10], [1, 1, 20, 10]],
        }
        selected, counts = select_numeric_annotation(
            row=row,
            shard_id="test",
            image_sha256="b" * 64,
            image_size=(100, 100),
        )
        self.assertEqual(selected["truth"], "12345")
        self.assertEqual(counts["numeric_annotations_in_scope"], 2)
        self.assertEqual(counts["unique_numeric_candidates"], 1)

    def test_missing_or_misaligned_fields_fail_closed(self) -> None:
        base = {
            "image": {"bytes": b"unused"},
            "id": 1,
            "words": ["12345"],
            "bboxes": [[1, 1, 20, 10]],
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


if __name__ == "__main__":
    unittest.main()
