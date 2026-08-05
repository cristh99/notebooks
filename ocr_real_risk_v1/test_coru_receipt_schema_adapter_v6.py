from __future__ import annotations

import copy
import unittest

from .coru_receipt_schema_adapter_v6 import (
    canonical_numeric_text,
    census_coco,
)


def coco_payload(*, include_text: bool = True) -> dict:
    annotations = [
        {
            "id": 1,
            "image_id": 10,
            "category_id": 1,
            "bbox": [1, 2, 20, 10],
            **({"transcription": "$12,345.67"} if include_text else {}),
        },
        {
            "id": 2,
            "image_id": 10,
            "category_id": 2,
            "bbox": [1, 20, 30, 10],
            **({"text": "TOTAL"} if include_text else {}),
        },
        {
            "id": 3,
            "image_id": 11,
            "category_id": 1,
            "bbox": [2, 3, 15, 8],
            **({"value": "2024"} if include_text else {}),
        },
    ]
    return {
        "images": [
            {"id": 10, "file_name": "images/a.jpg", "width": 100, "height": 200},
            {"id": 11, "file_name": "images/b.jpg", "width": 100, "height": 200},
        ],
        "annotations": annotations,
        "categories": [
            {"id": 1, "name": "total"},
            {"id": 2, "name": "store"},
        ],
    }


class CoruReceiptSchemaAdapterV6Tests(unittest.TestCase):
    def test_numeric_scope_is_explicit_and_ascii(self) -> None:
        self.assertEqual(canonical_numeric_text("$12,345.67"), "1234567")
        self.assertEqual(canonical_numeric_text("12 34"), "1234")
        self.assertIsNone(canonical_numeric_text("٢٠٢٤"))
        self.assertIsNone(canonical_numeric_text("2024"))
        self.assertIsNone(canonical_numeric_text("1111"))
        self.assertIsNone(canonical_numeric_text("ABC1234"))
        self.assertIsNone(canonical_numeric_text("123"))

    def test_coco_with_explicit_transcription_selects_one_per_image(self) -> None:
        report = census_coco(coco_payload(), ["total", "store"])
        self.assertTrue(report["supported_schema"])
        self.assertEqual(
            report["schema_status"],
            "SUPPORTED_COCO_WITH_EXPLICIT_NUMERIC_TRANSCRIPTIONS",
        )
        self.assertEqual(report["counts"]["images_total"], 2)
        self.assertEqual(
            report["counts"]["annotations_with_explicit_transcription"], 3
        )
        self.assertEqual(report["counts"]["numeric_annotations_in_scope"], 1)
        self.assertEqual(report["counts"]["images_with_numeric_candidate"], 1)
        self.assertEqual(len(report["selected_records"]), 1)
        self.assertEqual(report["selected_records"][0]["truth"], "1234567")
        self.assertEqual(
            report["selected_records"][0]["bbox_xyxy"],
            [1.0, 2.0, 21.0, 12.0],
        )
        self.assertEqual(len(report["selected_record_set_sha256"]), 64)

    def test_coco_without_transcriptions_is_terminal_not_invented_truth(self) -> None:
        report = census_coco(
            coco_payload(include_text=False), ["total", "store"]
        )
        self.assertTrue(report["supported_schema"])
        self.assertEqual(
            report["schema_status"],
            "COCO_WITHOUT_EXPLICIT_TRANSCRIPTION_FIELDS",
        )
        self.assertEqual(report["selected_records"], [])
        self.assertEqual(
            report["counts"]["annotations_without_explicit_transcription"],
            3,
        )

    def test_non_coco_schema_is_terminal_no_ocr(self) -> None:
        report = census_coco([{"image": "a.jpg"}], ["total"])
        self.assertFalse(report["supported_schema"])
        self.assertEqual(
            report["schema_status"],
            "TOP_LEVEL_JSON_IS_NOT_AN_OBJECT",
        )

    def test_conflicting_transcription_fields_fail_closed(self) -> None:
        payload = coco_payload()
        payload["annotations"][0]["text"] = "9999"
        with self.assertRaisesRegex(RuntimeError, "conflicting explicit"):
            census_coco(payload, ["total", "store"])

    def test_duplicate_image_id_and_filename_fail_closed(self) -> None:
        duplicate_id = coco_payload()
        duplicate_id["images"].append(
            {"id": 10, "file_name": "images/c.jpg"}
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate CORU COCO image id"):
            census_coco(duplicate_id, ["total", "store"])

        duplicate_name = coco_payload()
        duplicate_name["images"].append(
            {"id": 12, "file_name": "images/a.jpg"}
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate CORU COCO filename"):
            census_coco(duplicate_name, ["total", "store"])

    def test_invalid_bbox_and_unknown_image_fail_closed(self) -> None:
        invalid_bbox = coco_payload()
        invalid_bbox["annotations"][0]["bbox"] = [1, 2, 0, 10]
        with self.assertRaisesRegex(RuntimeError, "non-positive extent"):
            census_coco(invalid_bbox, ["total", "store"])

        unknown_image = coco_payload()
        unknown_image["annotations"][0]["image_id"] = 999
        with self.assertRaisesRegex(RuntimeError, "unknown image"):
            census_coco(unknown_image, ["total", "store"])

    def test_selection_is_order_independent(self) -> None:
        payload = coco_payload()
        payload["annotations"].append(
            {
                "id": 4,
                "image_id": 10,
                "category_id": 1,
                "bbox": [10, 30, 20, 10],
                "transcription": "98.76",
            }
        )
        first = census_coco(payload, ["total", "store"])
        reordered = copy.deepcopy(payload)
        reordered["annotations"] = list(reversed(reordered["annotations"]))
        second = census_coco(reordered, ["total", "store"])
        self.assertEqual(first["selected_records"], second["selected_records"])
        self.assertEqual(
            first["selected_record_set_sha256"],
            second["selected_record_set_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
