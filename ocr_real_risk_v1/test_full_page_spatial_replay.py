from __future__ import annotations

import unittest

from PIL import Image

from .full_page_spatial_replay import (
    _crop_box,
    _truth_bbox_pixels,
    eligibility,
    match_ocr_claim,
)


class FullPageSpatialReplayTests(unittest.TestCase):
    def test_match_prefers_token_covering_truth_location(self) -> None:
        truth = [100.0, 100.0, 160.0, 130.0]
        tokens = [
            {
                "text": "9999",
                "bbox": [300, 300, 360, 330],
                "confidence": 99.0,
            },
            {
                "text": "1234",
                "bbox": [98, 99, 162, 131],
                "confidence": 80.0,
            },
        ]
        matched = match_ocr_claim(truth, tokens)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["text"], "1234")
        self.assertGreater(matched["match"]["truth_coverage"], 0.95)

    def test_equal_length_wrong_claim_is_an_eligible_baseline_error(self) -> None:
        claim, eligible, reason = eligibility(
            "1234",
            {
                "text": "1284",
                "match": {"truth_coverage": 0.90},
            },
        )
        self.assertEqual(claim, "1284")
        self.assertTrue(eligible)
        self.assertEqual(reason, "ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM")

    def test_length_mismatch_is_outside_substitution_scope(self) -> None:
        claim, eligible, reason = eligibility(
            "1234",
            {
                "text": "12345",
                "match": {"truth_coverage": 1.0},
            },
        )
        self.assertEqual(claim, "12345")
        self.assertFalse(eligible)
        self.assertEqual(reason, "LENGTH_MISMATCH_OUTSIDE_SUBSTITUTION_SCOPE")

    def test_pdf_bbox_maps_to_rendered_page_geometry(self) -> None:
        image = Image.new("RGB", (1800, 2400), "white")
        pixels = _truth_bbox_pixels(
            {
                "page_width_pt": 600.0,
                "page_height_pt": 800.0,
                "bbox_pt": [100.0, 20.0, 200.0, 30.0],
            },
            image,
        )
        self.assertEqual(pixels, [300.0, 60.0, 600.0, 90.0])

    def test_matched_token_crop_is_clipped_with_two_pixel_margin(self) -> None:
        image = Image.new("RGB", (100, 80), "white")
        self.assertEqual(
            _crop_box(image, [-1.0, 5.0, 30.0, 20.0], margin=2),
            (0, 3, 32, 22),
        )


if __name__ == "__main__":
    unittest.main()
