"""Outcome-blind, fail-closed fusion of numeric token boxes across OCR PSMs.

The module does not invoke an OCR engine. It fuses already-produced token boxes,
counts support by distinct page-segmentation mode (PSM), rejects spatially
coincident disagreements, and emits deterministic evidence receipts. It is a
research component only and never grants production or external-validation
status.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import unicodedata
from dataclasses import asdict, dataclass
from typing import Iterable, Literal, Sequence

DetectorStatus = Literal["OK", "DUPLICATE_SOURCE_ID", "RESOURCE_LIMIT"]
ClusterStatus = Literal[
    "CONSENSUS",
    "AMBIGUOUS_CONFLICT",
    "INSUFFICIENT_PSM_SUPPORT",
]

_ASCII_DIGITS = frozenset("0123456789")
_ALLOWED_NON_DIGIT = frozenset(" \t\r\n.,:+-/$€£¥₹₡₦₱()[]{}'")
_CURRENCY_CODE = re.compile(
    r"(?i)\b(?:HNL|LPS?|L|USD|US|EUR|GBP|JPY|CNY|RMB|MYR|RM)\b"
)


@dataclass(frozen=True, slots=True)
class TokenObservation:
    """One OCR token with an independently traceable source identifier."""

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float
    psm: int
    source_id: str

    def __post_init__(self) -> None:
        text = str(self.text)
        source_id = str(self.source_id).strip()
        if not source_id:
            raise ValueError("source_id must be non-empty")
        if len(self.bbox) != 4:
            raise ValueError("bbox must contain exactly four coordinates")
        bbox = tuple(float(value) for value in self.bbox)
        if not all(math.isfinite(value) for value in bbox):
            raise ValueError("bbox coordinates must be finite")
        x0, y0, x1, y1 = bbox
        if x1 <= x0 or y1 <= y0:
            raise ValueError("bbox must have positive width and height")
        confidence = float(self.confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 100.0:
            raise ValueError("confidence must be finite and within [0, 100]")
        psm = int(self.psm)
        if psm <= 0:
            raise ValueError("psm must be positive")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "bbox", bbox)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "psm", psm)
        object.__setattr__(self, "source_id", source_id)


@dataclass(frozen=True, slots=True)
class DetectorPolicy:
    """Conservative geometric and evidence thresholds for token fusion."""

    min_psm_support: int = 2
    min_confidence: float = 0.0
    min_iou: float = 0.20
    min_smaller_coverage: float = 0.65
    min_vertical_overlap: float = 0.60
    min_digits: int = 4
    max_digits: int = 12
    max_observations: int = 10_000
    max_candidates: int = 1_000

    def __post_init__(self) -> None:
        if self.min_psm_support < 1:
            raise ValueError("min_psm_support must be positive")
        if not 0.0 <= self.min_confidence <= 100.0:
            raise ValueError("min_confidence must be within [0, 100]")
        for label, value in (
            ("min_iou", self.min_iou),
            ("min_smaller_coverage", self.min_smaller_coverage),
            ("min_vertical_overlap", self.min_vertical_overlap),
        ):
            if not math.isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError(f"{label} must be within (0, 1]")
        if self.min_digits < 1 or self.max_digits < self.min_digits:
            raise ValueError("digit-length bounds are invalid")
        if self.max_observations < 1 or self.max_candidates < 1:
            raise ValueError("resource limits must be positive")


@dataclass(frozen=True, slots=True)
class DetectionCandidate:
    status: ClusterStatus
    digits: str
    alternatives: tuple[str, ...]
    representative_text: str
    bbox: tuple[float, float, float, float]
    envelope_bbox: tuple[float, float, float, float]
    observations: int
    psm_support: int
    psms: tuple[int, ...]
    median_confidence: float
    source_ids: tuple[str, ...]
    cluster_sha256: str


@dataclass(frozen=True, slots=True)
class DetectionResult:
    status: DetectorStatus
    observations_total: int
    observations_used: int
    filtered_non_numeric: int
    filtered_low_confidence: int
    clusters: tuple[DetectionCandidate, ...]
    accepted: tuple[DetectionCandidate, ...]
    ambiguous: tuple[DetectionCandidate, ...]
    insufficient: tuple[DetectionCandidate, ...]
    result_sha256: str


@dataclass(frozen=True, slots=True)
class _Prepared:
    observation: TokenObservation
    digits: str


def canonical_numeric_token(
    value: str,
    *,
    min_digits: int,
    max_digits: int,
) -> str | None:
    """Return ASCII digits for a self-contained numeric-like token."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    without_codes = _CURRENCY_CODE.sub("", normalized).strip()
    unexpected = {
        character
        for character in without_codes
        if character not in _ASCII_DIGITS and character not in _ALLOWED_NON_DIGIT
    }
    if unexpected:
        return None
    digits = "".join(character for character in without_codes if character in _ASCII_DIGITS)
    if not min_digits <= len(digits) <= max_digits:
        return None
    return digits


def _geometry(
    first: Sequence[float],
    second: Sequence[float],
) -> tuple[float, float, float]:
    ax0, ay0, ax1, ay1 = map(float, first)
    bx0, by0, bx1, by1 = map(float, second)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    intersection_width = max(0.0, ix1 - ix0)
    intersection_height = max(0.0, iy1 - iy0)
    intersection = intersection_width * intersection_height
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    union = max(1e-12, area_a + area_b - intersection)
    smaller = max(1e-12, min(area_a, area_b))
    min_height = max(1e-12, min(ay1 - ay0, by1 - by0))
    return (
        intersection / union,
        intersection / smaller,
        intersection_height / min_height,
    )


def _compatible(
    first: _Prepared,
    second: _Prepared,
    policy: DetectorPolicy,
) -> tuple[bool, float]:
    iou, smaller_coverage, vertical_overlap = _geometry(
        first.observation.bbox,
        second.observation.bbox,
    )
    compatible = bool(
        vertical_overlap >= policy.min_vertical_overlap
        and (
            iou >= policy.min_iou
            or smaller_coverage >= policy.min_smaller_coverage
        )
    )
    return compatible, max(iou, smaller_coverage) if compatible else 0.0


def _prepared_sort_key(row: _Prepared) -> tuple[object, ...]:
    x0, y0, x1, y1 = row.observation.bbox
    return (
        y0,
        x0,
        y1,
        x1,
        row.observation.psm,
        row.digits,
        row.observation.source_id,
    )


def _cluster_complete_link(
    rows: Sequence[_Prepared],
    policy: DetectorPolicy,
) -> list[list[_Prepared]]:
    clusters: list[list[_Prepared]] = []
    for row in sorted(rows, key=_prepared_sort_key):
        compatible: list[tuple[float, int]] = []
        for cluster_index, cluster in enumerate(clusters):
            scores: list[float] = []
            for member in cluster:
                matches, score = _compatible(row, member, policy)
                if not matches:
                    break
                scores.append(score)
            else:
                compatible.append((min(scores), cluster_index))
        if not compatible:
            clusters.append([row])
            continue
        _, selected_index = max(
            compatible,
            key=lambda item: (item[0], -item[1]),
        )
        clusters[selected_index].append(row)
    return clusters


def _median_bbox(rows: Sequence[_Prepared]) -> tuple[float, float, float, float]:
    return tuple(
        float(statistics.median(row.observation.bbox[index] for row in rows))
        for index in range(4)
    )  # type: ignore[return-value]


def _envelope_bbox(rows: Sequence[_Prepared]) -> tuple[float, float, float, float]:
    return (
        min(row.observation.bbox[0] for row in rows),
        min(row.observation.bbox[1] for row in rows),
        max(row.observation.bbox[2] for row in rows),
        max(row.observation.bbox[3] for row in rows),
    )


def _candidate_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate(cluster: Sequence[_Prepared], policy: DetectorPolicy) -> DetectionCandidate:
    ordered = sorted(cluster, key=_prepared_sort_key)
    by_digits: dict[str, list[_Prepared]] = {}
    for row in ordered:
        by_digits.setdefault(row.digits, []).append(row)
    alternatives = tuple(sorted(by_digits))

    if len(alternatives) > 1:
        status: ClusterStatus = "AMBIGUOUS_CONFLICT"
        digits = ""
        supporting = ordered
        representative_text = ""
    else:
        digits = alternatives[0]
        supporting = by_digits[digits]
        psm_support = len({row.observation.psm for row in supporting})
        status = (
            "CONSENSUS"
            if psm_support >= policy.min_psm_support
            else "INSUFFICIENT_PSM_SUPPORT"
        )
        representative = max(
            supporting,
            key=lambda row: (
                row.observation.confidence,
                -row.observation.psm,
                row.observation.source_id,
            ),
        )
        representative_text = representative.observation.text

    psms = tuple(sorted({row.observation.psm for row in supporting}))
    source_ids = tuple(sorted(row.observation.source_id for row in supporting))
    bbox = _median_bbox(ordered)
    envelope = _envelope_bbox(ordered)
    confidence = float(
        statistics.median(row.observation.confidence for row in supporting)
    )
    payload: dict[str, object] = {
        "schema": "ocr-multi-psm-numeric-cluster-v4/1",
        "status": status,
        "digits": digits,
        "alternatives": alternatives,
        "representative_text": representative_text,
        "bbox": bbox,
        "envelope_bbox": envelope,
        "observations": len(ordered),
        "psm_support": len(psms),
        "psms": psms,
        "median_confidence": confidence,
        "source_ids": source_ids,
        "members": [
            {
                "text": row.observation.text,
                "digits": row.digits,
                "bbox": row.observation.bbox,
                "confidence": row.observation.confidence,
                "psm": row.observation.psm,
                "source_id": row.observation.source_id,
            }
            for row in ordered
        ],
        "policy": asdict(policy),
    }
    return DetectionCandidate(
        status=status,
        digits=digits,
        alternatives=alternatives,
        representative_text=representative_text,
        bbox=bbox,
        envelope_bbox=envelope,
        observations=len(ordered),
        psm_support=len(psms),
        psms=psms,
        median_confidence=confidence,
        source_ids=source_ids,
        cluster_sha256=_candidate_hash(payload),
    )


def _cluster_sort_key(row: DetectionCandidate) -> tuple[object, ...]:
    x0, y0, x1, y1 = row.bbox
    return (y0, x0, y1, x1, row.status, row.digits, row.alternatives)


def _finish(
    *,
    status: DetectorStatus,
    observations_total: int,
    observations_used: int,
    filtered_non_numeric: int,
    filtered_low_confidence: int,
    clusters: tuple[DetectionCandidate, ...],
    policy: DetectorPolicy,
) -> DetectionResult:
    accepted = tuple(row for row in clusters if row.status == "CONSENSUS")
    ambiguous = tuple(row for row in clusters if row.status == "AMBIGUOUS_CONFLICT")
    insufficient = tuple(
        row for row in clusters if row.status == "INSUFFICIENT_PSM_SUPPORT"
    )
    payload = {
        "schema": "ocr-multi-psm-numeric-detector-v4/1",
        "status": status,
        "observations_total": observations_total,
        "observations_used": observations_used,
        "filtered_non_numeric": filtered_non_numeric,
        "filtered_low_confidence": filtered_low_confidence,
        "clusters": [asdict(row) for row in clusters],
        "policy": asdict(policy),
    }
    result_sha256 = _candidate_hash(payload)
    return DetectionResult(
        status=status,
        observations_total=observations_total,
        observations_used=observations_used,
        filtered_non_numeric=filtered_non_numeric,
        filtered_low_confidence=filtered_low_confidence,
        clusters=clusters,
        accepted=accepted,
        ambiguous=ambiguous,
        insufficient=insufficient,
        result_sha256=result_sha256,
    )


def fuse_multi_psm_tokens(
    observations: Iterable[TokenObservation],
    *,
    policy: DetectorPolicy | None = None,
) -> DetectionResult:
    """Fuse token boxes without consulting truth labels or OCR outcomes."""

    active_policy = policy or DetectorPolicy()
    rows = list(observations)
    if len(rows) > active_policy.max_observations:
        return _finish(
            status="RESOURCE_LIMIT",
            observations_total=len(rows),
            observations_used=0,
            filtered_non_numeric=0,
            filtered_low_confidence=0,
            clusters=(),
            policy=active_policy,
        )
    source_ids = [row.source_id for row in rows]
    if len(source_ids) != len(set(source_ids)):
        return _finish(
            status="DUPLICATE_SOURCE_ID",
            observations_total=len(rows),
            observations_used=0,
            filtered_non_numeric=0,
            filtered_low_confidence=0,
            clusters=(),
            policy=active_policy,
        )

    prepared: list[_Prepared] = []
    filtered_non_numeric = 0
    filtered_low_confidence = 0
    for row in rows:
        if row.confidence < active_policy.min_confidence:
            filtered_low_confidence += 1
            continue
        digits = canonical_numeric_token(
            row.text,
            min_digits=active_policy.min_digits,
            max_digits=active_policy.max_digits,
        )
        if digits is None:
            filtered_non_numeric += 1
            continue
        prepared.append(_Prepared(observation=row, digits=digits))

    raw_clusters = _cluster_complete_link(prepared, active_policy)
    if len(raw_clusters) > active_policy.max_candidates:
        return _finish(
            status="RESOURCE_LIMIT",
            observations_total=len(rows),
            observations_used=len(prepared),
            filtered_non_numeric=filtered_non_numeric,
            filtered_low_confidence=filtered_low_confidence,
            clusters=(),
            policy=active_policy,
        )
    clusters = tuple(
        sorted(
            (_candidate(cluster, active_policy) for cluster in raw_clusters),
            key=_cluster_sort_key,
        )
    )
    return _finish(
        status="OK",
        observations_total=len(rows),
        observations_used=len(prepared),
        filtered_non_numeric=filtered_non_numeric,
        filtered_low_confidence=filtered_low_confidence,
        clusters=clusters,
        policy=active_policy,
    )
