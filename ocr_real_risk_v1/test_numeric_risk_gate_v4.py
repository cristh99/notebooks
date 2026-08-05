from __future__ import annotations

import unittest

from .numeric_context_v4 import ContextStatus
from .numeric_risk_gate_v4 import GateAction, decide_numeric_risk
from .pixel_digit_alignment_v4 import AlignmentStatus


class NumericRiskGateV4Tests(unittest.TestCase):
    def test_accept_requires_visual_and_context_consistency(self) -> None:
        decision = decide_numeric_risk(
            claim="11245",
            pixel_status=AlignmentStatus.ALIGNED,
            context_status=ContextStatus.CONSISTENT,
            pixel_receipt_sha256="a" * 64,
            context_receipt_sha256="b" * 64,
        )
        self.assertEqual(decision.action, GateAction.ACCEPT)
        self.assertIsNone(decision.replacement_value)

    def test_context_conflict_quarantines_even_when_pixels_align(self) -> None:
        decision = decide_numeric_risk(
            claim="11246",
            pixel_status=AlignmentStatus.ALIGNED,
            context_status=ContextStatus.CONFLICT,
            pixel_receipt_sha256="a" * 64,
            context_receipt_sha256="b" * 64,
        )
        self.assertEqual(decision.action, GateAction.QUARANTINE)
        self.assertEqual(decision.reason_code, "SEMANTIC_CONTEXT_CONFLICT")

    def test_visual_misalignment_quarantines(self) -> None:
        decision = decide_numeric_risk(
            claim="8400",
            pixel_status=AlignmentStatus.MISALIGNED,
            context_status=ContextStatus.INSUFFICIENT,
            pixel_receipt_sha256="a" * 64,
            context_receipt_sha256="b" * 64,
        )
        self.assertEqual(decision.action, GateAction.QUARANTINE)
        self.assertEqual(decision.reason_code, "PIXEL_MISALIGNMENT")

    def test_indeterminate_visual_claim_acquires_more_evidence(self) -> None:
        decision = decide_numeric_risk(
            claim="2890",
            pixel_status=AlignmentStatus.INDETERMINATE,
            context_status=ContextStatus.INSUFFICIENT,
            pixel_receipt_sha256="a" * 64,
            context_receipt_sha256="b" * 64,
        )
        self.assertEqual(decision.action, GateAction.ACQUIRE_MORE_EVIDENCE)

    def test_aligned_but_context_insufficient_does_not_auto_accept(self) -> None:
        decision = decide_numeric_risk(
            claim="1234",
            pixel_status=AlignmentStatus.ALIGNED,
            context_status=ContextStatus.INSUFFICIENT,
            pixel_receipt_sha256="a" * 64,
            context_receipt_sha256="b" * 64,
        )
        self.assertEqual(decision.action, GateAction.ACQUIRE_MORE_EVIDENCE)
        self.assertEqual(decision.reason_code, "CONTEXT_NOT_SEPARATING")

    def test_missing_receipt_fails_closed(self) -> None:
        decision = decide_numeric_risk(
            claim="1234",
            pixel_status=AlignmentStatus.ALIGNED,
            context_status=ContextStatus.CONSISTENT,
            pixel_receipt_sha256=None,
            context_receipt_sha256="b" * 64,
        )
        self.assertEqual(decision.action, GateAction.ACQUIRE_MORE_EVIDENCE)
        self.assertEqual(decision.reason_code, "MISSING_EVIDENCE_RECEIPT")

    def test_non_ascii_or_empty_claim_is_rejected(self) -> None:
        for claim in ("", "12.34", "١٢٣٤"):
            with self.assertRaises(ValueError):
                decide_numeric_risk(
                    claim=claim,
                    pixel_status=AlignmentStatus.ALIGNED,
                    context_status=ContextStatus.CONSISTENT,
                    pixel_receipt_sha256="a" * 64,
                    context_receipt_sha256="b" * 64,
                )

    def test_receipt_is_deterministic(self) -> None:
        first = decide_numeric_risk(
            claim="11245",
            pixel_status=AlignmentStatus.ALIGNED,
            context_status=ContextStatus.CONSISTENT,
            pixel_receipt_sha256="a" * 64,
            context_receipt_sha256="b" * 64,
        )
        second = decide_numeric_risk(
            claim="11245",
            pixel_status=AlignmentStatus.ALIGNED,
            context_status=ContextStatus.CONSISTENT,
            pixel_receipt_sha256="a" * 64,
            context_receipt_sha256="b" * 64,
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
