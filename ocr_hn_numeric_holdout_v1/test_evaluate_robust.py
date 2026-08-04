from __future__ import annotations

import unittest

import fitz
from PIL import Image

from .evaluate_robust import (
    robust_pil_page,
    rotation_aware_pdf_bbox_to_pixels,
    sanitize_numeric_tokens,
)


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

    def test_rotated_pdf_bbox_maps_inside_rendered_image(self) -> None:
        document = fitz.open()
        page = document.new_page(width=595, height=842)
        page.insert_text((100, 200), "3814", fontsize=12)
        bbox = page.get_text("rawdict")["blocks"][0]["lines"][0]["spans"][0]["bbox"]
        page.set_rotation(90)
        image = robust_pil_page(page, 300)
        pixels = rotation_aware_pdf_bbox_to_pixels(bbox, 300)
        self.assertGreater(pixels[2], pixels[0])
        self.assertGreater(pixels[3], pixels[1])
        self.assertGreaterEqual(pixels[0], 0)
        self.assertGreaterEqual(pixels[1], 0)
        self.assertLessEqual(pixels[2], image.width)
        self.assertLessEqual(pixels[3], image.height)
        # A naive unrotated scaling maps the token to a different quadrant.
        simple = [float(value) * 300 / 72 for value in bbox]
        self.assertNotAlmostEqual(pixels[0], simple[0], places=3)
        self.assertNotAlmostEqual(pixels[1], simple[1], places=3)
        document.close()

    def test_unrotated_pdf_bbox_remains_simple_dpi_scaling(self) -> None:
        document = fitz.open()
        page = document.new_page(width=300, height=200)
        page.insert_text((40, 70), "109071", fontsize=12)
        bbox = page.get_text("rawdict")["blocks"][0]["lines"][0]["spans"][0]["bbox"]
        image = robust_pil_page(page, 300)
        pixels = rotation_aware_pdf_bbox_to_pixels(bbox, 300)
        expected = [float(value) * 300 / 72 for value in bbox]
        for observed, target in zip(pixels, expected, strict=True):
            self.assertAlmostEqual(observed, target, places=4)
        self.assertLessEqual(pixels[2], image.width)
        self.assertLessEqual(pixels[3], image.height)
        document.close()


if __name__ == "__main__":
    unittest.main()
