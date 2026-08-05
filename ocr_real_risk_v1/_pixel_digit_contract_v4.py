"""Typed contract and deterministic primitives for pixel digit alignment v4."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASCII_DIGITS = frozenset("0123456789")
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


@dataclass(frozen=True, slots=True)
class AlignmentThresholds:
    aligned_absolute: float = 0.69
    aligned_margin: float = 0.012
    mismatch_absolute: float = 0.74
    mismatch_delta: float = 0.08
    mismatch_margin: float = 0.015

    def __post_init__(self) -> None:
        values = asdict(self).values()
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("thresholds must be finite and within [0, 1]")


@dataclass(frozen=True, slots=True)
class SegmentationPolicy:
    max_claim_length: int = 32
    punctuation_height_ratio: float = 0.42
    punctuation_area_ratio: float = 0.30
    minimum_patch_ink_fraction: float = 0.01
    maximum_patch_ink_fraction: float = 0.80

    def __post_init__(self) -> None:
        if self.max_claim_length < 1:
            raise ValueError("max_claim_length must be positive")
        ratios = (
            self.punctuation_height_ratio,
            self.punctuation_area_ratio,
            self.minimum_patch_ink_fraction,
            self.maximum_patch_ink_fraction,
        )
        if any(not math.isfinite(value) or not 0.0 < value < 1.0 for value in ratios):
            raise ValueError("segmentation ratios must be finite and within (0, 1)")
        if self.minimum_patch_ink_fraction >= self.maximum_patch_ink_fraction:
            raise ValueError("patch ink bounds are inconsistent")


@dataclass(frozen=True, slots=True)
class PositionDecision:
    index: int
    claim: str
    predicted: str
    state: str
    top_score: float
    claim_score: float
    top_margin: float
    mismatch_delta: float
    ink_fraction: float


@dataclass(frozen=True, slots=True)
class AlignmentDecision:
    status: AlignmentStatus
    claim: str
    predicted: str
    positions: tuple[PositionDecision, ...]
    cuts: tuple[int, ...]
    image_sha256: str
    configuration_sha256: str
    decision_sha256: str

    def to_data(self, *, include_positions: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status.value,
            "claim": self.claim,
            "predicted": self.predicted,
            "cuts": list(self.cuts),
            "image_sha256": self.image_sha256,
            "configuration_sha256": self.configuration_sha256,
            "decision_sha256": self.decision_sha256,
        }
        if include_positions:
            payload["positions"] = [asdict(position) for position in self.positions]
        return payload


def sha256_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ascii_digit_string(value: str) -> bool:
    return bool(value) and all(character in ASCII_DIGITS for character in value)


def font_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def image_sha256(image: Image.Image) -> str:
    array = np.asarray(image.convert("L"), dtype=np.uint8)
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("ascii"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


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
    """Render a deterministic synthetic ASCII-numeric token."""

    if not ascii_digit_string(text):
        raise ValueError("text must be a non-empty ASCII digit string")
    if size < 8 or spacing < 0 or stroke < 0:
        raise ValueError("render parameters are invalid")
    font = ImageFont.truetype(font_path, size)
    scratch = ImageDraw.Draw(Image.new("L", (1, 1), 255))
    boxes = [
        scratch.textbbox((0, 0), character, font=font, stroke_width=stroke)
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
    for character, box, width in zip(text, boxes, widths, strict=True):
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
        image = Image.fromarray(
            np.clip(array + generator.normal(0, noise, array.shape), 0, 255).astype(np.uint8)
        )
    return image


def existing_unique_fonts(fonts: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    output = tuple(str(Path(font)) for font in fonts if Path(font).is_file())
    if not output:
        raise ValueError("at least one existing template font is required")
    if len(set(output)) != len(output):
        raise ValueError("template fonts must be unique")
    return output
