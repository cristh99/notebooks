from __future__ import annotations

import unittest
from PIL import Image, ImageDraw, ImageFont

from .semantic_pixel_rival_v4_2 import (
    RivalAction,
    RivalPolicy,
    SemanticPixelRivalResolverV42,
)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def decimal_token(text: str) -> Image.Image:
    font = ImageFont.truetype(FONT, 44)
    canvas = Image.new("L", (240, 80), 255)
    ImageDraw.Draw(canvas).text((8, 8), text, font=font, fill=0)
    box = canvas.getbbox()
    return canvas.crop(box) if box else canvas


class SemanticPixelRivalV42Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolver = SemanticPixelRivalResolverV42()
        cls.resolver.warm()

    def test_invalid_rival_contract_is_rejected(self) -> None:
        page = decimal_token("15.00")
        for baseline, rival in (("", "1500"), ("1400", "15000"), ("1400", "1590")):
            with self.assertRaises(ValueError):
                self.resolver.resolve(page, (0, 0, page.width, page.height), baseline, rival)

    def test_pixel_rival_replacement_is_deterministic(self) -> None:
        page = decimal_token("15.00")
        first = self.resolver.resolve(page, (0, 0, page.width, page.height), "1400", "1500")
        second = self.resolver.resolve(page, (0, 0, page.width, page.height), "1400", "1500")
        self.assertEqual(first, second)
        self.assertEqual(first.action, RivalAction.REPLACE)
        self.assertEqual(first.output, "1500")
        self.assertEqual([view.predicted for view in first.views], ["1500", "1500"])

    def test_correct_pixels_reject_wrong_semantic_rival(self) -> None:
        page = decimal_token("17.45")
        decision = self.resolver.resolve(
            page, (0, 0, page.width, page.height), "1745", "1744"
        )
        self.assertEqual(decision.action, RivalAction.QUARANTINE)
        self.assertEqual(decision.output, "1745")

    def test_high_evidence_bar_can_force_quarantine(self) -> None:
        strict = SemanticPixelRivalResolverV42(
            aligner=self.resolver.aligner,
            policy=RivalPolicy(minimum_rival_advantage=0.99),
        )
        page = decimal_token("15.00")
        decision = strict.resolve(page, (0, 0, page.width, page.height), "1400", "1500")
        self.assertEqual(decision.action, RivalAction.QUARANTINE)

    def test_resource_limit_fails_closed(self) -> None:
        constrained = SemanticPixelRivalResolverV42(
            aligner=self.resolver.aligner,
            policy=RivalPolicy(maximum_runs=1),
        )
        page = decimal_token("15.00")
        decision = constrained.resolve(page, (0, 0, page.width, page.height), "1400", "1500")
        self.assertEqual(decision.action, RivalAction.QUARANTINE)
        self.assertEqual(decision.reason_code, "PIXEL_PARTITION_INDETERMINATE")


if __name__ == "__main__":
    unittest.main()
