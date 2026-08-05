"""Resolve one outcome-blind semantic OCR rival directly from pixels.

V4.2 is deliberately narrow. A semantic contradiction must first supply exactly
one same-length, one-digit rival. The resolver then recognizes the disputed crop
through two fixed pixel views using run-aware segmentation. It replaces only
when both views independently produce the complete rival and each gives the
rival digit a declared score advantage over the baseline digit. Every other
state quarantines; the module never restores a disputed baseline.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

import numpy as np
from PIL import Image, ImageOps

from ._pixel_digit_contract_v4 import ASCII_DIGITS
from ._pixel_digit_features_v4 import ink
from .pixel_digit_alignment_v4 import PixelDigitAlignerV4


class RivalAction(str, Enum):
    REPLACE = "REPLACE"
    QUARANTINE = "QUARANTINE"


@dataclass(frozen=True, slots=True)
class RivalPolicy:
    minimum_rival_advantage: float = 0.025
    minimum_rival_score: float = 0.74
    maximum_runs: int = 20
    maximum_partitions: int = 10_000
    punctuation_vertical_start: float = 0.45
    width_ratio_upper: float = 0.85
    width_ratio_lower: float = 0.12

    def __post_init__(self) -> None:
        probabilities = (
            self.minimum_rival_advantage,
            self.minimum_rival_score,
            self.punctuation_vertical_start,
            self.width_ratio_upper,
            self.width_ratio_lower,
        )
        if any(not math.isfinite(value) or not 0.0 < value < 1.0 for value in probabilities):
            raise ValueError("policy ratios must be finite and within (0, 1)")
        if self.width_ratio_lower >= self.width_ratio_upper:
            raise ValueError("width-ratio bounds are inconsistent")
        if self.maximum_runs < 1 or self.maximum_partitions < 1:
            raise ValueError("resource limits must be positive")


@dataclass(frozen=True, slots=True)
class RunPosition:
    index: int
    predicted: str
    top_score: float
    second_score: float
    top_margin: float
    baseline_score: float
    rival_score: float
    rival_advantage: float
    run_count: int
    x_start: int
    x_end: int


@dataclass(frozen=True, slots=True)
class PixelViewDecision:
    view_id: str
    predicted: str
    partition_quality: float
    positions: tuple[RunPosition, ...]


@dataclass(frozen=True, slots=True)
class PixelRivalDecision:
    action: RivalAction
    reason_code: str
    baseline: str
    rival: str
    output: str
    changed_position: int
    views: tuple[PixelViewDecision, ...]
    decision_sha256: str


def _ascii_digits(value: str) -> bool:
    return bool(value) and all(character in ASCII_DIGITS for character in value)


def _changed_position(baseline: str, rival: str) -> int:
    if not _ascii_digits(baseline) or not _ascii_digits(rival):
        raise ValueError("baseline and rival must be non-empty ASCII digit strings")
    if len(baseline) != len(rival):
        raise ValueError("baseline and rival must have equal length")
    changed = [index for index, pair in enumerate(zip(baseline, rival, strict=True)) if pair[0] != pair[1]]
    if len(changed) != 1:
        raise ValueError("v4.2 requires exactly one disputed digit")
    return changed[0]


def _horizontal_runs(binary: np.ndarray) -> list[dict[str, int]]:
    projection = (binary > 0).sum(axis=0)
    runs: list[dict[str, int]] = []
    start: int | None = None
    for column, occupied in enumerate([*(projection > 0).tolist(), False]):
        if occupied and start is None:
            start = column
        elif not occupied and start is not None:
            patch = binary[:, start:column]
            rows, _ = np.where(patch > 0)
            runs.append(
                {
                    "x_start": start,
                    "x_end": column,
                    "height": int(rows.max() - rows.min() + 1),
                    "area": int((patch > 0).sum()),
                    "y_start": int(rows.min()),
                    "y_end": int(rows.max() + 1),
                }
            )
            start = None
    return runs


def _digit_runs(binary: np.ndarray, aligner: PixelDigitAlignerV4, policy: RivalPolicy) -> list[dict[str, int]]:
    runs = _horizontal_runs(binary)
    if not runs:
        return []
    maximum_height = max(run["height"] for run in runs)
    reference_areas = [
        run["area"] for run in runs if run["height"] >= 0.65 * maximum_height
    ] or [run["area"] for run in runs]
    reference_area = float(np.median(reference_areas))
    return [
        run
        for run in runs
        if not (
            run["height"] < maximum_height * aligner.segmentation.punctuation_height_ratio
            and run["area"] < reference_area * aligner.segmentation.punctuation_area_ratio
            and run["y_start"] > binary.shape[0] * policy.punctuation_vertical_start
        )
    ]


def _partition(
    binary: np.ndarray,
    length: int,
    baseline: str,
    rival: str,
    aligner: PixelDigitAlignerV4,
    policy: RivalPolicy,
) -> tuple[float, tuple[RunPosition, ...]] | None:
    runs = _digit_runs(binary, aligner, policy)
    if len(runs) < length or len(runs) > policy.maximum_runs:
        return None
    partitions = math.comb(len(runs) - 1, length - 1)
    if partitions > policy.maximum_partitions:
        return None

    best: tuple[float, tuple[int, ...], tuple[RunPosition, ...]] | None = None
    for cuts in itertools.combinations(range(1, len(runs)), length - 1):
        boundaries = (0, *cuts, len(runs))
        positions: list[RunPosition] = []
        total_quality = 0.0
        valid = True
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            x_start = runs[start]["x_start"]
            x_end = runs[end - 1]["x_end"]
            patch = binary[:, x_start:x_end]
            rows, columns = np.where(patch > 0)
            if not len(columns):
                valid = False
                break
            patch = patch[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]
            scores = aligner._digit_scores(patch)  # same sealed feature bank; no OCR text
            ranking = sorted(((score, digit) for digit, score in scores.items()), reverse=True)
            top_score, predicted = ranking[0]
            second_score = ranking[1][0]
            width_ratio = (x_end - x_start) / max(1, int(rows.max() - rows.min() + 1))
            penalty = (
                max(0.0, width_ratio - policy.width_ratio_upper) * 0.25
                + max(0.0, policy.width_ratio_lower - width_ratio) * 0.20
                + max(0, (end - start) - 2) * 0.05
            )
            total_quality += top_score + 0.25 * (top_score - second_score) - penalty
            positions.append(
                RunPosition(
                    index=index,
                    predicted=predicted,
                    top_score=top_score,
                    second_score=second_score,
                    top_margin=top_score - second_score,
                    baseline_score=scores[baseline[index]],
                    rival_score=scores[rival[index]],
                    rival_advantage=scores[rival[index]] - scores[baseline[index]],
                    run_count=end - start,
                    x_start=x_start,
                    x_end=x_end,
                )
            )
        if not valid:
            continue
        candidate = (total_quality, cuts, tuple(positions))
        if best is None or candidate[0] > best[0] or (
            math.isclose(candidate[0], best[0], rel_tol=0.0, abs_tol=1e-12)
            and candidate[1] < best[1]
        ):
            best = candidate
    if best is None:
        return None
    return best[0], best[2]


def _view(page: Image.Image, bbox: Sequence[int], *, pad: int, scale: int) -> Image.Image:
    if len(bbox) != 4:
        raise ValueError("bbox must contain four coordinates")
    left, top, right, bottom = (int(value) for value in bbox)
    if right <= left or bottom <= top:
        raise ValueError("bbox must be non-empty")
    box = (
        max(0, left - pad),
        max(0, top - pad),
        min(page.width, right + pad),
        min(page.height, bottom + pad),
    )
    crop = ImageOps.autocontrast(page.crop(box).convert("L"), cutoff=1)
    if scale > 1:
        crop = crop.resize(
            (crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS
        )
    return crop


class SemanticPixelRivalResolverV42:
    """Two-view pixel resolver for one semantic one-digit rival."""

    VIEW_SPECS: tuple[tuple[str, int, int], ...] = (
        ("pad2_scale1", 2, 1),
        ("pad6_scale3", 6, 3),
    )

    def __init__(
        self,
        aligner: PixelDigitAlignerV4 | None = None,
        policy: RivalPolicy = RivalPolicy(),
    ) -> None:
        self.aligner = aligner or PixelDigitAlignerV4()
        self.policy = policy

    def warm(self) -> None:
        _ = self.aligner._bank

    def resolve(
        self,
        page: Image.Image,
        bbox: Sequence[int],
        baseline: str,
        rival: str,
    ) -> PixelRivalDecision:
        changed = _changed_position(baseline, rival)
        views: list[PixelViewDecision] = []
        failure = ""
        for view_id, pad, scale in self.VIEW_SPECS:
            source = _view(page, bbox, pad=pad, scale=scale)
            partition = _partition(
                ink(source),
                len(baseline),
                baseline,
                rival,
                self.aligner,
                self.policy,
            )
            if partition is None:
                failure = "PIXEL_PARTITION_INDETERMINATE"
                break
            quality, positions = partition
            predicted = "".join(position.predicted for position in positions)
            views.append(
                PixelViewDecision(
                    view_id=view_id,
                    predicted=predicted,
                    partition_quality=quality,
                    positions=positions,
                )
            )
            disputed = positions[changed]
            if predicted != rival:
                failure = "PIXEL_VIEWS_DO_NOT_PRODUCE_RIVAL"
                break
            if disputed.rival_score < self.policy.minimum_rival_score:
                failure = "RIVAL_PIXEL_SCORE_TOO_LOW"
                break
            if disputed.rival_advantage < self.policy.minimum_rival_advantage:
                failure = "RIVAL_PIXEL_ADVANTAGE_TOO_LOW"
                break

        if failure or len(views) != len(self.VIEW_SPECS):
            action = RivalAction.QUARANTINE
            reason = failure or "INCOMPLETE_PIXEL_EVIDENCE"
            output = baseline
        else:
            action = RivalAction.REPLACE
            reason = "SEMANTIC_RIVAL_CONFIRMED_BY_TWO_PIXEL_VIEWS"
            output = rival

        payload: dict[str, object] = {
            "schema": "ocr-semantic-pixel-rival-v4-2-decision/1",
            "action": action.value,
            "reason_code": reason,
            "baseline": baseline,
            "rival": rival,
            "output": output,
            "changed_position": changed,
            "policy": asdict(self.policy),
            "views": [asdict(view) for view in views],
        }
        decision_sha256 = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
        ).hexdigest()
        return PixelRivalDecision(
            action=action,
            reason_code=reason,
            baseline=baseline,
            rival=rival,
            output=output,
            changed_position=changed,
            views=tuple(views),
            decision_sha256=decision_sha256,
        )
