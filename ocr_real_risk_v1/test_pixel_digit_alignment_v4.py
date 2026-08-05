from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .pixel_digit_alignment_v4 import (
    AlignmentStatus,
    PixelDigitAlignerV4,
    render_numeric_token,
)

HOLDOUT = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
)


class PixelDigitAlignmentV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.aligner = PixelDigitAlignerV4()

    def test_correct_and_single_substitution_fail_closed(self) -> None:
        tokens = ("104729", "830156", "275940", "618203")
        aligned = 0
        detections = 0
        for font_index, font in enumerate(HOLDOUT):
            if not Path(font).is_file():
                continue
            for token_index, token in enumerate(tokens):
                image = render_numeric_token(
                    token,
                    font,
                    size=36 + token_index * 5,
                    angle=(-1.1, 0, 0.9, 0)[token_index],
                    blur=(0, 0.35)[token_index % 2],
                    noise=(0, 3)[token_index % 2],
                    seed=font_index * 100 + token_index,
                    spacing=token_index % 2,
                    stroke=(font_index + token_index) % 2,
                )
                correct = self.aligner.align(image, token)
                aligned += int(correct.status == AlignmentStatus.ALIGNED)
                self.assertNotEqual(correct.status, AlignmentStatus.MISALIGNED)
                position = (font_index + token_index) % len(token)
                altered = (
                    token[:position]
                    + str((int(token[position]) + 1) % 10)
                    + token[position + 1 :]
                )
                incorrect = self.aligner.align(image, altered)
                self.assertNotEqual(incorrect.status, AlignmentStatus.ALIGNED)
                detections += int(incorrect.status == AlignmentStatus.MISALIGNED)
        self.assertGreaterEqual(aligned, 16)
        self.assertGreaterEqual(detections, 16)

    def test_ascii_only_claims(self) -> None:
        font = next(font for font in HOLDOUT if Path(font).is_file())
        image = render_numeric_token("1234", font)
        for claim in ("", "12A4", "12.4", "١٢٣٤", "１２３４"):
            with self.assertRaises(ValueError):
                self.aligner.align(image, claim)

    def test_decimal_separator_is_removed_before_digit_segmentation(self) -> None:
        font_path = next(font for font in HOLDOUT if Path(font).is_file())
        font = ImageFont.truetype(font_path, 48)
        image = Image.new("L", (210, 80), 255)
        ImageDraw.Draw(image).text((10, 8), "80.91", font=font, fill=0)
        decision = self.aligner.align(image, "8091")
        self.assertNotEqual(decision.status, AlignmentStatus.MISALIGNED)
        self.assertEqual(len(decision.positions), 4)

    def test_receipts_are_deterministic_and_bound_to_pixels(self) -> None:
        font = next(font for font in HOLDOUT if Path(font).is_file())
        image = render_numeric_token("104729", font)
        first = self.aligner.align(image, "104729")
        second = self.aligner.align(image, "104729")
        self.assertEqual(first, second)
        altered = image.copy()
        ImageDraw.Draw(altered).point((0, 0), fill=0)
        third = self.aligner.align(altered, "104729")
        self.assertNotEqual(first.image_sha256, third.image_sha256)
        self.assertNotEqual(first.decision_sha256, third.decision_sha256)

    def test_configuration_declares_no_tesseract_or_network(self) -> None:
        configuration = self.aligner.configuration
        self.assertFalse(configuration["uses_tesseract"])
        self.assertFalse(configuration["uses_network"])
        self.assertEqual(len(configuration["template_fonts"]), 5)


if __name__ == "__main__":
    unittest.main()
