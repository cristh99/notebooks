"""Selective numeric-region OCR rescue experiment."""

from .rescue import (
    RescuePolicy,
    align_prediction_to_reference,
    apply_policy,
    classify_candidate,
    numeric_tokens,
    sequence_accuracy,
    summarize_candidates,
)

__all__ = [
    "RescuePolicy",
    "align_prediction_to_reference",
    "apply_policy",
    "classify_candidate",
    "numeric_tokens",
    "sequence_accuracy",
    "summarize_candidates",
]
