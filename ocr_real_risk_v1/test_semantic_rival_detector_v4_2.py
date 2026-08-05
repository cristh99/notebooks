from __future__ import annotations

import unittest

from .semantic_rival_detector_v4_2 import (
    SemanticOCRToken,
    SemanticRivalReason,
    detect_semantic_rivals,
)


def token(index: int, text: str, confidence: float, x: int, line: int) -> SemanticOCRToken:
    return SemanticOCRToken(
        index=index,
        text=text,
        bbox=(x, line * 40, x + 70, line * 40 + 25),
        confidence=confidence,
        block=1,
        paragraph=1,
        line=line,
    )


class SemanticRivalDetectorV42Tests(unittest.TestCase):
    def test_near_duplicate_emits_unique_rival(self) -> None:
        flags = detect_semantic_rivals(
            (
                token(1, "144.88", 74, 1300, 10),
                token(2, "144.68", 75, 1180, 20),
                token(3, "144.68", 58, 1180, 21),
            )
        )
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].token_index, 1)
        self.assertEqual(flags[0].baseline_digits, "14488")
        self.assertEqual(flags[0].rival_digits, "14468")
        self.assertFalse(flags[0].ambiguous)

    def test_qty_one_emits_other_amount_as_rival(self) -> None:
        flags = detect_semantic_rivals(
            (
                token(1, "1", 90, 500, 5),
                token(2, "29.90", 94, 590, 5),
                token(3, "28.90", 76, 730, 5),
            )
        )
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].token_index, 3)
        self.assertEqual(flags[0].rival_digits, "2990")
        self.assertEqual(
            flags[0].reasons,
            (SemanticRivalReason.QTY1_UNIT_AMOUNT_DISAGREEMENT,),
        )

    def test_multiple_rivals_are_preserved_as_ambiguous(self) -> None:
        flags = detect_semantic_rivals(
            (
                token(1, "144.88", 74, 1300, 10),
                token(2, "144.68", 80, 1180, 20),
                token(3, "144.68", 80, 1180, 21),
                token(4, "144.89", 80, 1180, 22),
                token(5, "144.89", 80, 1180, 23),
            )
        )
        self.assertEqual(len(flags), 1)
        self.assertTrue(flags[0].ambiguous)
        self.assertIsNone(flags[0].rival_digits)
        self.assertEqual(flags[0].all_rivals, ("14468", "14489"))
        self.assertIn(SemanticRivalReason.AMBIGUOUS_SEMANTIC_RIVALS, flags[0].reasons)

    def test_discount_row_with_three_amounts_is_ignored(self) -> None:
        self.assertEqual(
            detect_semantic_rivals(
                (
                    token(1, "1", 90, 500, 5),
                    token(2, "17.45", 90, 590, 5),
                    token(3, "0.00", 90, 680, 5),
                    token(4, "17.45", 90, 770, 5),
                )
            ),
            (),
        )

    def test_duplicate_indices_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            detect_semantic_rivals(
                (token(1, "29.90", 90, 590, 5), token(1, "28.90", 80, 730, 5))
            )


if __name__ == "__main__":
    unittest.main()
