"""Compose pixel and semantic evidence for high-risk OCR numeric claims.

This gate never manufactures a replacement. Acceptance requires two independent
separating families: pixels aligned with the claim and semantic context
consistent with it. Any explicit conflict quarantines; incomplete evidence
requests more evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum

from .numeric_context_v4 import ContextStatus
from .pixel_digit_alignment_v4 import AlignmentStatus

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ASCII_DIGITS = frozenset("0123456789")


class GateAction(str, Enum):
    ACCEPT = "ACCEPT"
    QUARANTINE = "QUARANTINE"
    ACQUIRE_MORE_EVIDENCE = "ACQUIRE_MORE_EVIDENCE"


@dataclass(frozen=True, slots=True)
class NumericRiskDecision:
    action: GateAction
    reason_code: str
    claim: str
    pixel_status: AlignmentStatus
    context_status: ContextStatus
    pixel_receipt_sha256: str | None
    context_receipt_sha256: str | None
    replacement_value: None
    decision_sha256: str


def _valid_receipt(value: str | None) -> bool:
    return value is not None and bool(_SHA256.fullmatch(value))


def decide_numeric_risk(
    *,
    claim: str,
    pixel_status: AlignmentStatus,
    context_status: ContextStatus,
    pixel_receipt_sha256: str | None,
    context_receipt_sha256: str | None,
) -> NumericRiskDecision:
    """Return a fail-closed action for one ASCII numeric claim."""

    claim = str(claim)
    if not claim or any(character not in _ASCII_DIGITS for character in claim):
        raise ValueError("claim must be a non-empty ASCII digit string")
    pixel_status = AlignmentStatus(pixel_status)
    context_status = ContextStatus(context_status)

    if not _valid_receipt(pixel_receipt_sha256) or not _valid_receipt(context_receipt_sha256):
        action = GateAction.ACQUIRE_MORE_EVIDENCE
        reason = "MISSING_EVIDENCE_RECEIPT"
    elif context_status == ContextStatus.CONFLICT:
        action = GateAction.QUARANTINE
        reason = "SEMANTIC_CONTEXT_CONFLICT"
    elif pixel_status == AlignmentStatus.MISALIGNED:
        action = GateAction.QUARANTINE
        reason = "PIXEL_MISALIGNMENT"
    elif pixel_status == AlignmentStatus.ALIGNED and context_status == ContextStatus.CONSISTENT:
        action = GateAction.ACCEPT
        reason = "INDEPENDENT_VISUAL_AND_CONTEXT_CONSENSUS"
    elif pixel_status == AlignmentStatus.INDETERMINATE:
        action = GateAction.ACQUIRE_MORE_EVIDENCE
        reason = "PIXEL_EVIDENCE_INDETERMINATE"
    else:
        action = GateAction.ACQUIRE_MORE_EVIDENCE
        reason = "CONTEXT_NOT_SEPARATING"

    payload = {
        "schema": "ocr-numeric-risk-gate-v4-decision/1",
        "action": action.value,
        "reason_code": reason,
        "claim": claim,
        "pixel_status": pixel_status.value,
        "context_status": context_status.value,
        "pixel_receipt_sha256": pixel_receipt_sha256,
        "context_receipt_sha256": context_receipt_sha256,
        "replacement_value": None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return NumericRiskDecision(
        action=action,
        reason_code=reason,
        claim=claim,
        pixel_status=pixel_status,
        context_status=context_status,
        pixel_receipt_sha256=pixel_receipt_sha256,
        context_receipt_sha256=context_receipt_sha256,
        replacement_value=None,
        decision_sha256=hashlib.sha256(encoded).hexdigest(),
    )
