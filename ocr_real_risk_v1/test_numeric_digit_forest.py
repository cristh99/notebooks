from __future__ import annotations

import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .numeric_digit_forest import (
    FEATURE_SCHEMA,
    MODEL_PARAMETERS,
    THRESHOLD,
    VIEW_NAMES,
    deterministic_views,
    digit_patch_feature,
    infer_claim,
    summarize_decisions,
)
from .pixel_digit_alignment import _ink


class _PatternModel:
    classes_ = np.arange(10)

    def __init__(self, pattern: str, confidence: float) -> None:
        self.pattern = pattern
        self.confidence = confidence

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        length = len(self.pattern)
        output = np.full(
            (matrix.shape[0], 10),
            (1.0 - self.confidence) / 9.0,
            dtype=float,
        )
        for row in range(matrix.shape[0]):
            position = row % length
            output[row, int(self.pattern[position])] = self.confidence
        return output


def _token_image(text: str) -> Image.Image:
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        42,
    )
    image = Image.new("L", (180, 70), 255)
    ImageDraw.Draw(image).text((10, 7), text, font=font, fill=0)
    return image


class NumericDigitForestTests(unittest.TestCase):
    def test_frozen_protocol_constants(self) -> None:
        self.assertEqual(FEATURE_SCHEMA, "ocr-numeric-digit-patch-feature/1")
        self.assertEqual(THRESHOLD, 0.25)
        self.assertEqual(
            VIEW_NAMES,
            ("original", "autocontrast2", "clahe2", "otsu2"),
        )
        self.assertEqual(MODEL_PARAMETERS["n_estimators"], 500)
        self.assertEqual(MODEL_PARAMETERS["min_samples_leaf"], 2)
        self.assertEqual(MODEL_PARAMETERS["max_features"], 0.2)
        self.assertEqual(MODEL_PARAMETERS["class_weight"], "balanced")

    def test_views_are_deterministic_and_dimensioned(self) -> None:
        image = _token_image("1234")
        first = deterministic_views(image)
        second = deterministic_views(image)
        self.assertEqual(tuple(first), VIEW_NAMES)
        self.assertEqual(tuple(second), VIEW_NAMES)
        for name in VIEW_NAMES:
            self.assertEqual(first[name].tobytes(), second[name].tobytes())
        self.assertEqual(first["original"].size, image.size)
        self.assertEqual(
            first["autocontrast2"].size,
            (image.width * 2, image.height * 2),
        )

    def test_patch_feature_is_finite_and_fixed_width(self) -> None:
        feature = digit_patch_feature(_ink(_token_image("8")))
        self.assertEqual(feature.shape, (1564,))
        self.assertEqual(feature.dtype, np.float32)
        self.assertTrue(np.all(np.isfinite(feature)))
        self.assertAlmostEqual(float(np.linalg.norm(feature)), 1.0, places=5)

    def test_inference_accepts_matching_high_probability_claim(self) -> None:
        result = infer_claim(
            _PatternModel("1234", 0.90),
            _token_image("1234"),
            "1234",
        )
        self.assertEqual(result["prediction"], "1234")
        self.assertTrue(result["accepted"])
        self.assertGreaterEqual(result["minimum_mean_probability"], 0.89)

    def test_inference_rejects_different_prediction(self) -> None:
        result = infer_claim(
            _PatternModel("1284", 0.90),
            _token_image("1234"),
            "1234",
        )
        self.assertEqual(result["prediction"], "1284")
        self.assertFalse(result["accepted"])

    def test_inference_rejects_matching_low_probability_claim(self) -> None:
        result = infer_claim(
            _PatternModel("1234", 0.20),
            _token_image("1234"),
            "1234",
        )
        self.assertEqual(result["prediction"], "1234")
        self.assertFalse(result["accepted"])
        self.assertLess(result["minimum_mean_probability"], THRESHOLD)

    def test_summary_separates_natural_and_counterfactual_failures(self) -> None:
        decisions = [
            {
                "key": "A",
                "natural_accepted": True,
                "natural_false_accept": False,
                "counterfactual_accepted": False,
            },
            {
                "key": "B",
                "natural_accepted": True,
                "natural_false_accept": True,
                "counterfactual_accepted": True,
            },
            {
                "key": "C",
                "natural_accepted": False,
                "natural_false_accept": False,
                "counterfactual_accepted": False,
            },
        ]
        summary = summarize_decisions(decisions, selected_locations=5)
        self.assertEqual(summary["eligible_claims"], 3)
        self.assertEqual(summary["accepted"], 2)
        self.assertEqual(summary["natural_false_accepts"], 1)
        self.assertEqual(summary["counterfactual_false_accepts"], 1)
        self.assertEqual(summary["natural_false_accept_keys"], ["B"])
        self.assertEqual(summary["counterfactual_false_accept_keys"], ["B"])


if __name__ == "__main__":
    unittest.main()
