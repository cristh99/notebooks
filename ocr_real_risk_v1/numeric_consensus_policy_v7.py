"""Preregistered numeric-claim verifier for OCR consensus v7.

This module is an engineering successor to TextOCR v6. TextOCR outcomes are
development data only. The policy is frozen before any COCO-Text footer, row,
annotation, image byte, OCR output, or benchmark outcome is opened.

The policy verifies an observed numeric claim; it never silently replaces that
claim with a different digit string. All inputs are inference-visible:
detector claim, detector conflicts, pixel-model prediction/probability, and
crop guard readings. Ground-truth text is deliberately absent.
"""
from __future__ import annotations

from typing import Any, Mapping

POLICY_SCHEMA = "ocr-numeric-consensus-policy/7"
POLICY_ID = "v7-claim-verifier-prob25-guard1-no-conflict"
FOREST_MINIMUM_MEAN_PROBABILITY = 0.25
MIN_DIGITS = 4
MAX_DIGITS = 12
ELIGIBILITY_MINIMUM_BBOX_COVERAGE = 0.50


def _digits(value: object) -> str:
    raw = str(value or "")
    return raw if raw.isdigit() else ""


def _candidate_values(row: Mapping[str, Any]) -> dict[str, str]:
    candidate = row.get("candidate")
    if not isinstance(candidate, Mapping):
        return {}
    claim = _digits(candidate.get("claim"))
    if not MIN_DIGITS <= len(claim) <= MAX_DIGITS:
        return {}
    guard = candidate.get("guard")
    matched = candidate.get("matched")
    if not isinstance(guard, Mapping) or not isinstance(matched, Mapping):
        return {}
    readings = guard.get("readings")
    if not isinstance(readings, Mapping):
        return {}
    raw = {
        "claim": claim,
        "forest": _digits(
            candidate.get("prediction")
            or candidate.get("forest_prediction")
        ),
        "gray": _digits(
            (readings.get("gray") or {}).get("digits")
            if isinstance(readings.get("gray"), Mapping)
            else ""
        ),
        "autocontrast": _digits(
            (readings.get("autocontrast") or {}).get("digits")
            if isinstance(readings.get("autocontrast"), Mapping)
            else ""
        ),
    }
    length = len(claim)
    return {
        name: value
        for name, value in raw.items()
        if value and len(value) == length
    }


def inference_eligibility(
    matched: Mapping[str, Any] | None,
) -> tuple[str, bool, str]:
    """Validate an inference-visible detector match without ground-truth text."""
    if not isinstance(matched, Mapping):
        return "", False, "NO_SPATIAL_MATCH"
    claim = _digits(matched.get("text"))
    if not claim:
        return "", False, "EMPTY_CLAIM"
    if not MIN_DIGITS <= len(claim) <= MAX_DIGITS:
        return claim, False, "CLAIM_LENGTH_OUTSIDE_DECLARED_SCOPE"
    match = matched.get("match")
    coverage = (
        float(match.get("truth_coverage") or 0.0)
        if isinstance(match, Mapping)
        else 0.0
    )
    if coverage < ELIGIBILITY_MINIMUM_BBOX_COVERAGE:
        return claim, False, "LOW_SPATIAL_COVERAGE"
    return claim, True, "ELIGIBLE_INFERENCE_VISIBLE_NUMERIC_CLAIM"


def predict_v7_claim_verifier(row: Mapping[str, Any]) -> str | None:
    """Return the detector claim only when independent evidence supports it.

    Fail-closed gates:
    * pixel model confidence is at least 0.25;
    * pixel model predicts exactly the detector claim;
    * detector cluster has no equal-length conflicting reading;
    * at least one independent crop guard agrees with the claim.

    The function cannot correct a claim to a different value. It either verifies
    the supplied claim or abstains.
    """
    candidate = row.get("candidate")
    if not isinstance(candidate, Mapping):
        return None
    values = _candidate_values(row)
    claim = values.get("claim")
    forest = values.get("forest")
    if not claim or forest != claim:
        return None
    probability = float(
        candidate.get("minimum_mean_probability") or 0.0
    )
    if probability < FOREST_MINIMUM_MEAN_PROBABILITY:
        return None
    matched = candidate.get("matched")
    if not isinstance(matched, Mapping):
        return None
    if matched.get("equal_length_conflicts"):
        return None
    guard_support = sum(
        values.get(name) == claim
        for name in ("gray", "autocontrast")
    )
    if guard_support < 1:
        return None
    return claim


def policy_manifest() -> dict[str, Any]:
    return {
        "schema": POLICY_SCHEMA,
        "policy_id": POLICY_ID,
        "semantics": "verify_observed_claim_or_abstain",
        "ground_truth_available_at_inference": False,
        "annotation_text_length_used_at_inference": False,
        "forest_minimum_mean_probability": (
            FOREST_MINIMUM_MEAN_PROBABILITY
        ),
        "forest_threshold_is_effective": True,
        "equal_length_detector_conflicts": "abstain",
        "minimum_independent_crop_guards": 1,
        "alternate_output_correction": False,
        "terminal_outputs": ["verified_claim", "abstain"],
    }
