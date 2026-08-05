from __future__ import annotations

import copy
import unittest

from .textocr_adapter_v6 import (
    DEVELOPMENT_ACCEPTANCE_RATE,
    canonical_numeric_text,
    census_rows,
    polygon_envelope,
    resolve_bbox,
    select_numeric_annotation,
)


class TextOcrAdapterV6Tests(unittest.TestCase):
    def test_numeric_scope_is_ascii_and_explicit(self) -> None:
        self.assertEqual(canonical_numeric_text("$12,345.67"), "1234567")
        self.assertEqual(canonical_numeric_text("12 34"), "1234")
        self.assertIsNone(canonical_numeric_text("٢٠٢٤"))
        self.assertIsNone(canonical_numeric_text("2024"))
        self.assertIsNone(canonical_numeric_text("1111"))
        self.assertIsNone(canonical_numeric_text("ABC1234"))
        self.assertIsNone(canonical_numeric_text("123"))
        self.assertIsNone(canonical_numeric_text("1234567890123"))

    def test_polygon_envelope_accepts_flat_and_nested_points(self) -> None:
        flat = polygon_envelope([1, 2, 11, 2, 11, 12, 1, 12])
        nested = polygon_envelope([[1, 2], [11, 2], [11, 12], [1, 12]])
        self.assertEqual(flat, (1.0, 2.0, 11.0, 12.0))
        self.assertEqual(flat, nested)
        with self.assertRaisesRegex(RuntimeError, "at least four"):
            polygon_envelope([1, 2, 3, 4, 5, 6])

    def test_bbox_convention_is_resolved_against_polygon(self) -> None:
        polygon = [10, 20, 40, 20, 40, 60, 10, 60]
        xyxy, convention, score = resolve_bbox([10, 20, 40, 60], polygon)
        self.assertEqual(xyxy, (10.0, 20.0, 40.0, 60.0))
        self.assertEqual(convention, "xyxy")
        self.assertEqual(score, 1.0)

        xywh, convention, score = resolve_bbox([10, 20, 30, 40], polygon)
        self.assertEqual(xywh, (10.0, 20.0, 40.0, 60.0))
        self.assertEqual(convention, "xywh")
        self.assertEqual(score, 1.0)

    def test_bbox_ambiguity_and_geometry_disagreement_fail_closed(self) -> None:
        # xyxy=(10,10,20,20) and xywh=(10,10,30,30) each have IoU .5
        # with the 20x10 polygon envelope, so the adapter must abstain.
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            resolve_bbox(
                [10, 10, 20, 20],
                [10, 10, 30, 10, 30, 20, 10, 20],
            )
        with self.assertRaisesRegex(RuntimeError, "disagrees"):
            resolve_bbox(
                [0, 0, 10, 10],
                [100, 100, 110, 100, 110, 110, 100, 110],
            )

    def test_selection_is_annotation_order_independent(self) -> None:
        texts = ["12,345", "TOTAL", "67.890"]
        bboxes = [[10, 20, 30, 10], [1, 1, 9, 9], [50, 20, 30, 10]]
        polygons = [
            [10, 20, 40, 20, 40, 30, 10, 30],
            [1, 1, 10, 1, 10, 10, 1, 10],
            [50, 20, 80, 20, 80, 30, 50, 30],
        ]
        first, first_counts = select_numeric_annotation(
            row_index=7,
            texts=texts,
            bboxes=bboxes,
            polygons=polygons,
            num_text_regions=3,
        )
        order = [2, 1, 0]
        second, second_counts = select_numeric_annotation(
            row_index=7,
            texts=[texts[index] for index in order],
            bboxes=[bboxes[index] for index in order],
            polygons=[polygons[index] for index in order],
            num_text_regions=3,
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        for field in (
            "truth",
            "bbox_xyxy",
            "bbox_convention",
            "selection_rank_sha256",
        ):
            self.assertEqual(first[field], second[field])
        self.assertEqual(first_counts["unique_numeric_candidates"], 2)
        self.assertEqual(second_counts["unique_numeric_candidates"], 2)

    def test_duplicate_physical_annotation_is_collapsed(self) -> None:
        selected, counts = select_numeric_annotation(
            row_index=8,
            texts=["12,345", "12345"],
            bboxes=[[10, 20, 30, 10], [10, 20, 30, 10]],
            polygons=[
                [10, 20, 40, 20, 40, 30, 10, 30],
                [10, 20, 40, 20, 40, 30, 10, 30],
            ],
            num_text_regions=2,
        )
        self.assertEqual(selected["truth"], "12345")
        self.assertEqual(counts["numeric_annotations_in_scope"], 2)
        self.assertEqual(counts["unique_numeric_candidates"], 1)

    def test_misaligned_arrays_and_count_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not one-to-one"):
            select_numeric_annotation(
                row_index=0,
                texts=["1234"],
                bboxes=[],
                polygons=[],
                num_text_regions=1,
            )
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            select_numeric_annotation(
                row_index=0,
                texts=["1234"],
                bboxes=[[0, 0, 10, 10]],
                polygons=[[0, 0, 10, 0, 10, 10, 0, 10]],
                num_text_regions=2,
            )

    def test_census_is_deterministic_and_one_unit_per_row(self) -> None:
        rows = [
            (
                0,
                ["1234"],
                [[0, 0, 10, 10]],
                [[0, 0, 10, 0, 10, 10, 0, 10]],
                1,
            ),
            (
                1,
                ["TEXT", "56.78"],
                [[0, 0, 10, 10], [20, 0, 10, 10]],
                [
                    [0, 0, 10, 0, 10, 10, 0, 10],
                    [20, 0, 30, 0, 30, 10, 20, 10],
                ],
                2,
            ),
            (
                2,
                ["NO DIGITS"],
                [[0, 0, 10, 10]],
                [[0, 0, 10, 0, 10, 10, 0, 10]],
                1,
            ),
        ]
        first = census_rows(rows)
        second = census_rows(copy.deepcopy(rows))
        self.assertEqual(first, second)
        self.assertEqual(first["row_count"], 3)
        self.assertEqual(first["selected_count"], 2)
        self.assertEqual(len(first["records"]), 2)
        self.assertEqual(len(first["selected_record_set_sha256"]), 64)
        self.assertAlmostEqual(DEVELOPMENT_ACCEPTANCE_RATE, 472 / 1720)

    def test_duplicate_row_index_fails_closed(self) -> None:
        rows = [
            (
                0,
                ["1234"],
                [[0, 0, 10, 10]],
                [[0, 0, 10, 0, 10, 10, 0, 10]],
                1,
            ),
            (
                0,
                ["5678"],
                [[0, 0, 10, 10]],
                [[0, 0, 10, 0, 10, 10, 0, 10]],
                1,
            ),
        ]
        with self.assertRaisesRegex(RuntimeError, "duplicate TextOCR row index"):
            census_rows(rows)


if __name__ == "__main__":
    unittest.main()
