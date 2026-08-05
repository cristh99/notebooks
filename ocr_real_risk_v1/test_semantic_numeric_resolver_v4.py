from __future__ import annotations

import unittest

from .semantic_numeric_resolver_v4 import (
    CropObservation,
    OCRToken,
    ResolutionAction,
    TriggerReason,
    canonical_ascii_digits,
    detect_semantic_flags,
    resolve_flagged_token,
)


def token(index: int, text: str, confidence: float, x: int, line: int) -> OCRToken:
    return OCRToken(
        index=index,
        text=text,
        bbox=(x, line * 40, x + 70, line * 40 + 25),
        confidence=confidence,
        block=1,
        paragraph=1,
        line=line,
    )


def observation(source: str, text: str, *, timeout: bool = False) -> CropObservation:
    return CropObservation(
        source_id=source,
        view=source,
        psm=7 if source == "a" else 13,
        text=text,
        elapsed_seconds=0.01,
        timeout=timeout,
    )


class SemanticNumericResolverV4Tests(unittest.TestCase):
    def test_ascii_canonicalization_excludes_non_ascii_digits(self) -> None:
        self.assertEqual(canonical_ascii_digits("RM 1,234.50"), "123450")
        self.assertEqual(canonical_ascii_digits("١٢٣٤"), "")

    def test_document_majority_flags_only_singleton_hamming_one(self) -> None:
        rows = (
            token(1, "144.88", 74, 1300, 10),
            token(2, "144.68", 75, 1180, 20),
            token(3, "144.68", 58, 1180, 21),
            token(4, "8.68", 94, 1370, 11),
        )
        flags = detect_semantic_flags(rows)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].token_index, 1)
        self.assertEqual(
            flags[0].reasons,
            (TriggerReason.NEAR_DUPLICATE_DOCUMENT_MAJORITY,),
        )

    def test_qty_one_disagreement_flags_lower_confidence_amount(self) -> None:
        rows = (
            token(1, "1X", 72, 500, 5),
            token(2, "29.90", 94, 590, 5),
            token(3, "28.90", 76, 730, 5),
        )
        flags = detect_semantic_flags(rows)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].token_index, 3)
        self.assertEqual(
            flags[0].reasons,
            (TriggerReason.QTY1_UNIT_AMOUNT_DISAGREEMENT,),
        )

    def test_discount_row_with_three_amounts_is_not_flagged(self) -> None:
        rows = (
            token(1, "1", 90, 500, 5),
            token(2, "17.45", 90, 590, 5),
            token(3, "0.00", 90, 680, 5),
            token(4, "17.45", 90, 770, 5),
        )
        self.assertEqual(detect_semantic_flags(rows), ())

    def test_two_probes_can_replace_same_length_alternative(self) -> None:
        decision = resolve_flagged_token(
            "28,90",
            (observation("a", "29.90"), observation("b", "29,90")),
        )
        self.assertEqual(decision.action, ResolutionAction.REPLACE)
        self.assertEqual(decision.output, "29,90")

    def test_same_engine_baseline_confirmation_does_not_clear_semantic_flag(self) -> None:
        decision = resolve_flagged_token(
            "29.90",
            (observation("a", "29.90"), observation("b", "29,90")),
        )
        self.assertEqual(decision.action, ResolutionAction.QUARANTINE)
        self.assertEqual(
            decision.reason_code,
            "SEMANTIC_CONTRADICTION_NOT_CLEARED_BY_SAME_ENGINE_PROBES",
        )
        self.assertEqual(decision.output, "29.90")

    def test_disagreement_or_duplicate_source_quarantines(self) -> None:
        disagreement = resolve_flagged_token(
            "28.90",
            (observation("a", "29.90"), observation("b", "28.90")),
        )
        self.assertEqual(disagreement.action, ResolutionAction.QUARANTINE)
        duplicate = resolve_flagged_token(
            "28.90",
            (observation("a", "29.90"), observation("a", "29.90")),
        )
        self.assertEqual(duplicate.action, ResolutionAction.QUARANTINE)

    def test_decision_hash_is_deterministic(self) -> None:
        first = resolve_flagged_token(
            "144.88",
            (observation("a", "144.68"), observation("b", "144.68")),
        )
        second = resolve_flagged_token(
            "144.88",
            (observation("a", "144.68"), observation("b", "144.68")),
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
