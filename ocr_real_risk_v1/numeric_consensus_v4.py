"""Fail-closed numeric OCR consensus and explicit 10x speed gate.

This module is a research policy layer. It never grants production status and
never changes a token unless independent evidence crosses every configured
threshold. Numeric substitutions preserve the baseline token's punctuation and
currency formatting, keeping v4 inside the equal-digit-length correction scope.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import asdict, dataclass
from typing import Iterable, Literal, Sequence

Action = Literal["KEEP", "REPLACE", "ABSTAIN"]

_ASCII_DIGITS = frozenset("0123456789")
_ALLOWED_NON_DIGIT = frozenset(" \t\r\n.,:+-/$€£¥₹₡₦₱()[]{}'")
_CURRENCY_CODE = re.compile(
    r"(?i)\b(?:HNL|LPS?|L|USD|US|EUR|GBP|JPY|CNY|RMB|MYR|RM)\b"
)


@dataclass(frozen=True, slots=True)
class Observation:
    """One independently identifiable OCR or model observation."""

    text: str
    source_id: str
    crop_family: str
    modality: str
    psm: int | None = None
    confidence: float = 1.0
    timeout: bool = False

    def __post_init__(self) -> None:
        source_id = str(self.source_id).strip()
        crop_family = str(self.crop_family).strip()
        modality = str(self.modality).strip().lower()
        if not source_id:
            raise ValueError("source_id must be non-empty")
        if not crop_family:
            raise ValueError("crop_family must be non-empty")
        if not modality:
            raise ValueError("modality must be non-empty")
        confidence = float(self.confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be finite and within [0, 1]")
        psm = None if self.psm is None else int(self.psm)
        if psm is not None and psm <= 0:
            raise ValueError("psm must be positive")
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "crop_family", crop_family)
        object.__setattr__(self, "modality", modality)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "psm", psm)


@dataclass(frozen=True, slots=True)
class ReplacementPolicy:
    """Evidence thresholds for a substitution-only numeric correction."""

    min_votes: int = 3
    min_crop_families: int = 2
    min_modalities: int = 2
    min_psms: int = 2
    min_observation_confidence: float = 0.0
    min_median_confidence: float = 0.80
    conflict_min_votes: int = 2
    min_vote_margin: int = 2
    max_observations: int = 1_000

    def __post_init__(self) -> None:
        integer_fields = (
            self.min_votes,
            self.min_crop_families,
            self.min_modalities,
            self.min_psms,
            self.conflict_min_votes,
            self.min_vote_margin,
        )
        if any(value < 1 for value in integer_fields):
            raise ValueError("all count thresholds must be positive")
        if self.max_observations < 1:
            raise ValueError("max_observations must be positive")
        if not 0.0 <= self.min_observation_confidence <= 1.0:
            raise ValueError("min_observation_confidence must be within [0, 1]")
        if not 0.0 <= self.min_median_confidence <= 1.0:
            raise ValueError("min_median_confidence must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class Support:
    digits: str
    votes: int
    crop_families: int
    modalities: int
    psms: int
    median_confidence: float
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplacementDecision:
    action: Action
    reason: str
    baseline: str
    output: str
    support: Support
    runner_up: Support | None
    decision_sha256: str


@dataclass(frozen=True, slots=True)
class SpeedGateResult:
    pass_gate: bool
    required_speedup: float
    sample_count_tesseract: int
    sample_count_candidate: int
    median_tesseract_ms: float
    median_candidate_ms: float
    p95_tesseract_ms: float
    p95_candidate_ms: float
    median_speedup: float
    p95_speedup: float


def _digits_if_numeric_like(value: str) -> str | None:
    """Return ASCII digits only for a safely numeric-like token."""

    without_codes = _CURRENCY_CODE.sub("", str(value or "").strip())
    unexpected = {
        character
        for character in without_codes
        if character not in _ASCII_DIGITS and character not in _ALLOWED_NON_DIGIT
    }
    if unexpected:
        return None
    digits = "".join(
        character for character in without_codes if character in _ASCII_DIGITS
    )
    return digits or None


def format_like_baseline(baseline: str, replacement_digits: str) -> str:
    """Insert replacement digits into the baseline's exact non-digit skeleton."""

    baseline_digits = _digits_if_numeric_like(baseline)
    if baseline_digits is None:
        raise ValueError("baseline is not a supported numeric-like token")
    if not replacement_digits or any(
        character not in _ASCII_DIGITS for character in replacement_digits
    ):
        raise ValueError("replacement_digits must contain ASCII digits only")
    if len(replacement_digits) != len(baseline_digits):
        raise ValueError("replacement must preserve the baseline digit count")
    iterator = iter(replacement_digits)
    return "".join(
        next(iterator) if character in _ASCII_DIGITS else character
        for character in baseline
    )


def _support(digits: str, observations: Sequence[Observation]) -> Support:
    psms = {
        int(row.psm)
        for row in observations
        if row.modality.lower() == "ocr" and row.psm is not None
    }
    return Support(
        digits=digits,
        votes=len(observations),
        crop_families=len({row.crop_family for row in observations}),
        modalities=len({row.modality.lower() for row in observations}),
        psms=len(psms),
        median_confidence=float(statistics.median(row.confidence for row in observations)),
        source_ids=tuple(sorted(row.source_id for row in observations)),
    )


def _empty_support(digits: str) -> Support:
    return Support(
        digits=digits,
        votes=0,
        crop_families=0,
        modalities=0,
        psms=0,
        median_confidence=0.0,
        source_ids=(),
    )


def _decision_hash(
    *,
    action: Action,
    reason: str,
    baseline: str,
    output: str,
    support: Support,
    runner_up: Support | None,
    policy: ReplacementPolicy,
) -> str:
    payload = {
        "schema": "ocr-numeric-consensus-v4-decision/1",
        "action": action,
        "reason": reason,
        "baseline": baseline,
        "output": output,
        "support": asdict(support),
        "runner_up": asdict(runner_up) if runner_up is not None else None,
        "policy": asdict(policy),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finish(
    *,
    action: Action,
    reason: str,
    baseline: str,
    output: str,
    support: Support,
    runner_up: Support | None,
    policy: ReplacementPolicy,
) -> ReplacementDecision:
    return ReplacementDecision(
        action=action,
        reason=reason,
        baseline=baseline,
        output=output,
        support=support,
        runner_up=runner_up,
        decision_sha256=_decision_hash(
            action=action,
            reason=reason,
            baseline=baseline,
            output=output,
            support=support,
            runner_up=runner_up,
            policy=policy,
        ),
    )


def decide_replacement(
    baseline: str,
    observations: Iterable[Observation],
    *,
    policy: ReplacementPolicy | None = None,
) -> ReplacementDecision:
    """Choose a safe same-length numeric replacement or abstain.

    Evidence is fail-closed. Duplicate source identifiers, unsupported token
    shapes, low diversity, low confidence, or independently supported conflicts
    all produce ``ABSTAIN``.
    """

    active_policy = policy or ReplacementPolicy()
    baseline_digits = _digits_if_numeric_like(baseline)
    if baseline_digits is None:
        empty = _empty_support("")
        return _finish(
            action="ABSTAIN",
            reason="UNSUPPORTED_BASELINE_TOKEN",
            baseline=baseline,
            output=baseline,
            support=empty,
            runner_up=None,
            policy=active_policy,
        )

    rows = list(observations)
    if len(rows) > active_policy.max_observations:
        empty = _empty_support(baseline_digits)
        return _finish(
            action="ABSTAIN",
            reason="RESOURCE_LIMIT",
            baseline=baseline,
            output=baseline,
            support=empty,
            runner_up=None,
            policy=active_policy,
        )
    source_ids = [row.source_id for row in rows]
    if len(source_ids) != len(set(source_ids)):
        empty = _empty_support(baseline_digits)
        return _finish(
            action="ABSTAIN",
            reason="DUPLICATE_SOURCE_ID",
            baseline=baseline,
            output=baseline,
            support=empty,
            runner_up=None,
            policy=active_policy,
        )

    grouped: dict[str, list[Observation]] = {}
    for row in rows:
        if row.timeout or row.confidence < active_policy.min_observation_confidence:
            continue
        digits = _digits_if_numeric_like(row.text)
        if digits is None or len(digits) != len(baseline_digits):
            continue
        grouped.setdefault(digits, []).append(row)

    supports = [_support(digits, evidence) for digits, evidence in grouped.items()]
    alternatives = [item for item in supports if item.digits != baseline_digits]
    alternatives.sort(
        key=lambda item: (
            item.votes,
            item.crop_families,
            item.modalities,
            item.psms,
            item.median_confidence,
            item.digits,
        ),
        reverse=True,
    )
    if not alternatives:
        empty = _empty_support(baseline_digits)
        return _finish(
            action="ABSTAIN",
            reason="NO_ELIGIBLE_ALTERNATIVE",
            baseline=baseline,
            output=baseline,
            support=empty,
            runner_up=None,
            policy=active_policy,
        )

    candidate = alternatives[0]
    other_supports = [item for item in supports if item.digits != candidate.digits]
    other_supports.sort(
        key=lambda item: (
            item.votes,
            item.crop_families,
            item.modalities,
            item.psms,
            item.median_confidence,
            item.digits,
        ),
        reverse=True,
    )
    runner_up = other_supports[0] if other_supports else None

    checks = (
        (candidate.votes >= active_policy.min_votes, "INSUFFICIENT_VOTES"),
        (
            candidate.crop_families >= active_policy.min_crop_families,
            "INSUFFICIENT_INDEPENDENT_CROPS",
        ),
        (
            candidate.modalities >= active_policy.min_modalities,
            "INSUFFICIENT_MODALITY_DIVERSITY",
        ),
        (candidate.psms >= active_policy.min_psms, "INSUFFICIENT_PSM_DIVERSITY"),
        (
            candidate.median_confidence >= active_policy.min_median_confidence,
            "LOW_MEDIAN_CONFIDENCE",
        ),
    )
    for passed, reason in checks:
        if not passed:
            return _finish(
                action="ABSTAIN",
                reason=reason,
                baseline=baseline,
                output=baseline,
                support=candidate,
                runner_up=runner_up,
                policy=active_policy,
            )

    if runner_up is not None and runner_up.votes >= active_policy.conflict_min_votes:
        independently_supported = bool(
            runner_up.crop_families >= 2
            or runner_up.modalities >= 2
            or runner_up.psms >= 2
        )
        if independently_supported:
            return _finish(
                action="ABSTAIN",
                reason="INDEPENDENT_CONFLICT",
                baseline=baseline,
                output=baseline,
                support=candidate,
                runner_up=runner_up,
                policy=active_policy,
            )
        if candidate.votes - runner_up.votes < active_policy.min_vote_margin:
            return _finish(
                action="ABSTAIN",
                reason="AMBIGUOUS_VOTE_MARGIN",
                baseline=baseline,
                output=baseline,
                support=candidate,
                runner_up=runner_up,
                policy=active_policy,
            )

    output = format_like_baseline(baseline, candidate.digits)
    return _finish(
        action="REPLACE",
        reason="INDEPENDENT_CONSENSUS",
        baseline=baseline,
        output=output,
        support=candidate,
        runner_up=runner_up,
        policy=active_policy,
    )


def _validated_timings(values: Sequence[float], label: str) -> list[float]:
    if len(values) < 5:
        raise ValueError(f"{label} requires at least five timings")
    output = [float(value) for value in values]
    if any(not math.isfinite(value) or value <= 0.0 for value in output):
        raise ValueError(f"{label} timings must be finite and positive")
    return sorted(output)


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    rank = max(1, math.ceil(percentile * len(values)))
    return float(values[rank - 1])


def speed_gate(
    *,
    tesseract_ms: Sequence[float],
    candidate_ms: Sequence[float],
    required_speedup: float = 10.0,
) -> SpeedGateResult:
    """Require both median and p95 candidate latency to beat Tesseract by 10x."""

    if not math.isfinite(required_speedup) or required_speedup <= 1.0:
        raise ValueError("required_speedup must be finite and greater than one")
    baseline = _validated_timings(tesseract_ms, "tesseract")
    candidate = _validated_timings(candidate_ms, "candidate")
    median_baseline = float(statistics.median(baseline))
    median_candidate = float(statistics.median(candidate))
    p95_baseline = _nearest_rank(baseline, 0.95)
    p95_candidate = _nearest_rank(candidate, 0.95)
    median_speedup = median_baseline / median_candidate
    p95_speedup = p95_baseline / p95_candidate
    return SpeedGateResult(
        pass_gate=bool(
            median_speedup >= required_speedup and p95_speedup >= required_speedup
        ),
        required_speedup=float(required_speedup),
        sample_count_tesseract=len(baseline),
        sample_count_candidate=len(candidate),
        median_tesseract_ms=median_baseline,
        median_candidate_ms=median_candidate,
        p95_tesseract_ms=p95_baseline,
        p95_candidate_ms=p95_candidate,
        median_speedup=median_speedup,
        p95_speedup=p95_speedup,
    )
