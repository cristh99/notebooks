"""Frozen runtime subset of the independent pixel digit verifier.

Source lineage:
- repository: ``cristh99/my_first_repository``
- commit: ``d48de2f44c3a2b6447c3a712adb263715f569dee``
- source path: ``ocr_power_v1/pixel_digit_alignment.py``

The runtime classifier, template bank, thresholds, segmentation and feature
vectors are preserved. Test-only rendering controls do not affect evaluation.
Vendoring removes a private cross-repository network dependency from CI while
keeping the verifier frozen and independently hashable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SOURCE_REPOSITORY = "cristh99/my_first_repository"
SOURCE_COMMIT = "d48de2f44c3a2b6447c3a712adb263715f569dee"
SOURCE_PATH = "ocr_power_v1/pixel_digit_alignment.py"

DEFAULT_TEMPLATE_FONTS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
    "/usr/share/fonts/opentype/inter/InterDisplay-Regular.otf",
)


class AlignmentStatus(str, Enum):
    ALIGNED = "ALIGNED"
    MISALIGNED = "MISALIGNED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class AlignmentThresholds:
    aligned_absolute: float = 0.69
    aligned_margin: float = 0.012
    mismatch_absolute: float = 0.74
    mismatch_delta: float = 0.08
    mismatch_margin: float = 0.015

    def to_data(self) -> dict[str, float]:
        return {
            "aligned_absolute": self.aligned_absolute,
            "aligned_margin": self.aligned_margin,
            "mismatch_absolute": self.mismatch_absolute,
            "mismatch_delta": self.mismatch_delta,
            "mismatch_margin": self.mismatch_margin,
        }


@dataclass(frozen=True)
class PositionDecision:
    index: int
    claim: str
    predicted: str
    state: str
    top_score: float
    claim_score: float
    top_margin: float
    mismatch_delta: float

    def to_data(self) -> dict[str, object]:
        return {
            "index": self.index,
            "claim": self.claim,
            "predicted": self.predicted,
            "state": self.state,
            "top_score": round(self.top_score, 9),
            "claim_score": round(self.claim_score, 9),
            "top_margin": round(self.top_margin, 9),
            "mismatch_delta": round(self.mismatch_delta, 9),
        }


@dataclass(frozen=True)
class AlignmentDecision:
    status: AlignmentStatus
    claim: str
    predicted: str
    positions: tuple[PositionDecision, ...]
    cuts: tuple[int, ...]

    def to_data(self, include_positions: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status.value,
            "claim": self.claim,
            "predicted": self.predicted,
            "cuts": list(self.cuts),
        }
        if include_positions:
            payload["positions"] = [
                position.to_data() for position in self.positions
            ]
        return payload


def render_numeric_token(
    text: str,
    font_path: str,
    *,
    size: int = 48,
    angle: float = 0,
    blur: float = 0,
    noise: float = 0,
    seed: int = 0,
    spacing: int = 0,
    stroke: int = 0,
) -> Image.Image:
    if not text or not text.isdigit():
        raise ValueError("text must be a non-empty digit string")
    font = ImageFont.truetype(font_path, size)
    scratch = ImageDraw.Draw(Image.new("L", (1, 1), 255))
    if spacing == 0:
        box = scratch.textbbox(
            (0, 0), text, font=font, stroke_width=stroke
        )
        image = Image.new(
            "L",
            (box[2] - box[0] + 28, box[3] - box[1] + 28),
            255,
        )
        ImageDraw.Draw(image).text(
            (14 - box[0], 14 - box[1]),
            text,
            font=font,
            fill=0,
            stroke_width=stroke,
            stroke_fill=0,
        )
    else:
        boxes = [
            scratch.textbbox(
                (0, 0), character, font=font, stroke_width=stroke
            )
            for character in text
        ]
        widths = [box[2] - box[0] for box in boxes]
        height = max(box[3] - box[1] for box in boxes) + 28
        image = Image.new(
            "L",
            (sum(widths) + spacing * (len(text) - 1) + 28, height),
            255,
        )
        draw = ImageDraw.Draw(image)
        x = 14
        for character, box, width in zip(
            text, boxes, widths, strict=True
        ):
            draw.text(
                (x - box[0], 14 - box[1]),
                character,
                font=font,
                fill=0,
                stroke_width=stroke,
                stroke_fill=0,
            )
            x += width + spacing
    if angle:
        image = image.rotate(
            angle,
            expand=True,
            fillcolor=255,
            resample=Image.Resampling.BICUBIC,
        )
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        array = np.array(image, dtype=np.int16)
        generator = np.random.default_rng(seed)
        array = np.clip(
            array + generator.normal(0, noise, array.shape),
            0,
            255,
        ).astype(np.uint8)
        image = Image.fromarray(array)
    return image


def _ink(image: Image.Image) -> np.ndarray:
    array = np.array(image.convert("L"))
    array = cv2.GaussianBlur(array, (3, 3), 0)
    _, binary = cv2.threshold(
        array,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    components, labels, stats, _ = cv2.connectedComponentsWithStats(
        (binary > 0).astype(np.uint8), 8
    )
    cleaned = np.zeros_like(binary)
    minimum_area = max(2, int(binary.size * 0.0003))
    for component in range(1, components):
        if stats[component, cv2.CC_STAT_AREA] >= minimum_area:
            cleaned[labels == component] = 255
    rows, columns = np.where(cleaned > 0)
    if not len(columns):
        return np.zeros((1, 1), np.uint8)
    return cleaned[
        rows.min() : rows.max() + 1,
        columns.min() : columns.max() + 1,
    ]


def _normalize(
    binary: np.ndarray,
    shape: tuple[int, int] = (64, 48),
) -> np.ndarray:
    height, width = shape
    rows, columns = np.where(binary > 0)
    if not len(columns):
        return np.zeros(shape, np.uint8)
    binary = binary[
        rows.min() : rows.max() + 1,
        columns.min() : columns.max() + 1,
    ]
    source_height, source_width = binary.shape
    scale = min(
        (height - 10) / source_height,
        (width - 10) / source_width,
    )
    resized_width = max(1, round(source_width * scale))
    resized_height = max(1, round(source_height * scale))
    resized = cv2.resize(
        binary,
        (resized_width, resized_height),
        interpolation=(
            cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        ),
    )
    _, resized = cv2.threshold(
        resized, 127, 255, cv2.THRESH_BINARY
    )
    result = np.zeros(shape, np.uint8)
    y = (height - resized_height) // 2
    x = (width - resized_width) // 2
    result[y : y + resized_height, x : x + resized_width] = resized
    return result


def _projection_cuts(
    binary: np.ndarray,
    length: int,
) -> tuple[int, ...]:
    _, width = binary.shape
    if length <= 1:
        return (0, width)
    projection = (binary > 0).sum(axis=0).astype(float)
    projection = np.convolve(
        projection, np.ones(3) / 3, mode="same"
    )
    expected_width = width / length
    cuts = [0]
    for index in range(1, length):
        center = index * expected_width
        low = max(
            cuts[-1] + 1,
            int(center - expected_width * 0.35),
        )
        high = min(
            width - 1,
            int(center + expected_width * 0.35) + 1,
        )
        if low >= high:
            cut = round(center)
        else:
            cut = min(
                range(low, high),
                key=lambda column: (
                    projection[column]
                    + 0.15 * abs(column - center),
                    abs(column - center),
                    column,
                ),
            )
        cuts.append(cut)
    cuts.append(width)
    return tuple(cuts)


def _segment(
    binary: np.ndarray,
    length: int,
) -> tuple[tuple[np.ndarray, ...], tuple[int, ...]]:
    cuts = _projection_cuts(binary, length)
    patches: list[np.ndarray] = []
    for left, right in zip(cuts, cuts[1:]):
        patch = binary[:, left:right]
        rows, columns = np.where(patch > 0)
        if len(columns):
            patch = patch[
                rows.min() : rows.max() + 1,
                columns.min() : columns.max() + 1,
            ]
        patches.append(patch)
    return tuple(patches), cuts


class PixelDigitAligner:
    """Deterministic abstaining numeric-token pixel verifier."""

    _shape = (64, 48)
    _hog = cv2.HOGDescriptor(
        _winSize=(48, 64),
        _blockSize=(16, 16),
        _blockStride=(8, 8),
        _cellSize=(8, 8),
        _nbins=9,
    )

    def __init__(
        self,
        template_fonts: Iterable[str] = DEFAULT_TEMPLATE_FONTS,
        thresholds: AlignmentThresholds = AlignmentThresholds(),
    ) -> None:
        fonts = tuple(
            str(Path(font))
            for font in template_fonts
            if Path(font).exists()
        )
        if not fonts:
            raise ValueError(
                "at least one existing template font is required"
            )
        if len(set(fonts)) != len(fonts):
            raise ValueError("template fonts must be unique")
        self.template_fonts = fonts
        self.thresholds = thresholds

    @classmethod
    def _feature(cls, binary: np.ndarray) -> np.ndarray:
        normalized = _normalize(binary, cls._shape)
        hog = cls._hog.compute(normalized).ravel().astype(np.float32)
        low_resolution = (
            cv2.resize(
                normalized,
                (12, 16),
                interpolation=cv2.INTER_AREA,
            )
            .ravel()
            .astype(np.float32)
            / 255
        )
        horizontal = (normalized > 0).mean(axis=1).astype(np.float32)
        vertical = (normalized > 0).mean(axis=0).astype(np.float32)
        vector = np.concatenate(
            [
                hog,
                low_resolution * 0.8,
                horizontal * 0.5,
                vertical * 0.5,
            ]
        )
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    @cached_property
    def _bank(self) -> tuple[np.ndarray, np.ndarray]:
        features: list[np.ndarray] = []
        labels: list[str] = []
        for digit in "0123456789":
            for font in self.template_fonts:
                for size in (42, 52, 62):
                    for angle in (-2, -1, 0, 1, 2):
                        for stroke in (0, 1):
                            image = render_numeric_token(
                                digit,
                                font,
                                size=size,
                                angle=angle,
                                stroke=stroke,
                            )
                            features.append(
                                self._feature(_ink(image))
                            )
                            labels.append(digit)
        return np.vstack(features), np.array(labels)

    def _digit_scores(self, patch: np.ndarray) -> dict[str, float]:
        features, labels = self._bank
        similarities = features @ self._feature(patch)
        scores: dict[str, float] = {}
        for digit in "0123456789":
            top = np.sort(similarities[labels == digit])[-7:]
            scores[digit] = float(top.mean())
        return scores

    def align(
        self,
        image: Image.Image | str | Path,
        claim: str,
    ) -> AlignmentDecision:
        if not claim or not claim.isdigit():
            raise ValueError("claim must be a non-empty digit string")
        if len(claim) > 64:
            raise ValueError(
                "claim is too long for a single-token alignment probe"
            )
        if isinstance(image, (str, Path)):
            with Image.open(image) as opened:
                source = opened.convert("L")
        elif isinstance(image, Image.Image):
            source = image.convert("L")
        else:
            raise TypeError(
                "image must be a PIL image or filesystem path"
            )
        patches, cuts = _segment(_ink(source), len(claim))
        positions: list[PositionDecision] = []
        predicted: list[str] = []
        thresholds = self.thresholds
        for index, (patch, claimed_digit) in enumerate(
            zip(patches, claim, strict=True)
        ):
            scores = self._digit_scores(patch)
            ranking = sorted(
                (
                    (score, digit)
                    for digit, score in scores.items()
                ),
                reverse=True,
            )
            top_score, top_digit = ranking[0]
            second_score = ranking[1][0]
            claim_score = scores[claimed_digit]
            top_margin = top_score - second_score
            mismatch_delta = top_score - claim_score
            if (
                top_digit == claimed_digit
                and top_score >= thresholds.aligned_absolute
                and top_margin >= thresholds.aligned_margin
            ):
                state = AlignmentStatus.ALIGNED.value
            elif (
                top_digit != claimed_digit
                and top_score >= thresholds.mismatch_absolute
                and mismatch_delta >= thresholds.mismatch_delta
                and top_margin >= thresholds.mismatch_margin
            ):
                state = "MISMATCH_CANDIDATE"
            else:
                state = AlignmentStatus.INDETERMINATE.value
            predicted.append(top_digit)
            positions.append(
                PositionDecision(
                    index=index,
                    claim=claimed_digit,
                    predicted=top_digit,
                    state=state,
                    top_score=top_score,
                    claim_score=claim_score,
                    top_margin=top_margin,
                    mismatch_delta=mismatch_delta,
                )
            )
        states = [position.state for position in positions]
        if all(
            state == AlignmentStatus.ALIGNED.value
            for state in states
        ):
            status = AlignmentStatus.ALIGNED
        elif (
            states.count("MISMATCH_CANDIDATE") == 1
            and states.count(AlignmentStatus.ALIGNED.value)
            == len(states) - 1
        ):
            status = AlignmentStatus.MISALIGNED
        else:
            status = AlignmentStatus.INDETERMINATE
        return AlignmentDecision(
            status=status,
            claim=claim,
            predicted="".join(predicted),
            positions=tuple(positions),
            cuts=cuts,
        )

    def configuration(self) -> dict[str, object]:
        return {
            "schema": "ocr-power-v1/pixel-digit-alignment-config/1",
            "source_repository": SOURCE_REPOSITORY,
            "source_commit": SOURCE_COMMIT,
            "source_path": SOURCE_PATH,
            "template_fonts": list(self.template_fonts),
            "thresholds": self.thresholds.to_data(),
            "feature_shape": list(self._shape),
        }
