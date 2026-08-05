"""Fail-closed pixel-to-digit verifier selected by Logic Power v10.

V4 is limited to one printed numeric token. It adds ASCII-only claims,
punctuation removal, resource limits, canonical receipts, and no dependency on
Tesseract or network services. It never promotes an alternative token by itself.
"""
from __future__ import annotations

from dataclasses import asdict
from functools import cached_property
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image

from ._pixel_digit_contract_v4 import (
    AlignmentDecision,
    AlignmentStatus,
    AlignmentThresholds,
    DEFAULT_TEMPLATE_FONTS,
    PositionDecision,
    SegmentationPolicy,
    ascii_digit_string,
    existing_unique_fonts,
    font_sha256,
    image_sha256,
    render_numeric_token,
    sha256_payload,
)
from ._pixel_digit_features_v4 import SHAPE, feature, ink, remove_punctuation, segment

__all__ = [
    "AlignmentDecision",
    "AlignmentStatus",
    "AlignmentThresholds",
    "PixelDigitAlignerV4",
    "PositionDecision",
    "SegmentationPolicy",
    "render_numeric_token",
]


class PixelDigitAlignerV4:
    """Deterministic verifier returning ALIGNED, MISALIGNED, or INDETERMINATE."""

    def __init__(
        self,
        template_fonts: Iterable[str] = DEFAULT_TEMPLATE_FONTS,
        thresholds: AlignmentThresholds = AlignmentThresholds(),
        segmentation: SegmentationPolicy = SegmentationPolicy(),
    ) -> None:
        self.template_fonts = existing_unique_fonts(tuple(template_fonts))
        self.thresholds = thresholds
        self.segmentation = segmentation

    @cached_property
    def _bank(self) -> tuple[np.ndarray, np.ndarray]:
        features: list[np.ndarray] = []
        labels: list[str] = []
        for digit in "0123456789":
            for font in self.template_fonts:
                for size in (42, 52, 62):
                    for angle in (-2, -1, 0, 1, 2):
                        for stroke in (0, 1):
                            features.append(
                                feature(
                                    ink(
                                        render_numeric_token(
                                            digit,
                                            font,
                                            size=size,
                                            angle=angle,
                                            stroke=stroke,
                                        )
                                    )
                                )
                            )
                            labels.append(digit)
        return np.vstack(features), np.array(labels)

    def _digit_scores(self, patch: np.ndarray) -> dict[str, float]:
        features, labels = self._bank
        similarities = features @ feature(patch)
        return {
            digit: float(np.sort(similarities[labels == digit])[-7:].mean())
            for digit in "0123456789"
        }

    @cached_property
    def configuration(self) -> dict[str, object]:
        return {
            "schema": "ocr-pixel-digit-alignment-v4-config/1",
            "source_sha": "a7f9cbc74aad41e05ef851ba6edb79978905700e",
            "template_fonts": [
                {"path": font, "sha256": font_sha256(font)}
                for font in self.template_fonts
            ],
            "thresholds": asdict(self.thresholds),
            "segmentation": asdict(self.segmentation),
            "feature": {
                "normalized_shape": list(SHAPE),
                "template_sizes": [42, 52, 62],
                "template_angles": [-2, -1, 0, 1, 2],
                "template_strokes": [0, 1],
                "templates_per_digit": len(self.template_fonts) * 3 * 5 * 2,
            },
            "uses_tesseract": False,
            "uses_network": False,
        }

    @cached_property
    def configuration_sha256(self) -> str:
        return sha256_payload(self.configuration)

    def align(self, image: Image.Image | str | Path, claim: str) -> AlignmentDecision:
        if not ascii_digit_string(claim):
            raise ValueError("claim must be a non-empty ASCII digit string")
        if len(claim) > self.segmentation.max_claim_length:
            raise ValueError("claim exceeds the single-token resource limit")
        if isinstance(image, (str, Path)):
            with Image.open(image) as opened:
                source = opened.convert("L")
        elif isinstance(image, Image.Image):
            source = image.convert("L")
        else:
            raise TypeError("image must be a PIL image or filesystem path")

        image_hash = image_sha256(source)
        binary = remove_punctuation(ink(source), self.segmentation)
        patches, cuts = segment(binary, len(claim))
        positions: list[PositionDecision] = []
        predicted: list[str] = []
        for index, (patch, claimed_digit) in enumerate(zip(patches, claim, strict=True)):
            ink_fraction = float((patch > 0).mean()) if patch.size else 0.0
            if not (
                self.segmentation.minimum_patch_ink_fraction
                <= ink_fraction
                <= self.segmentation.maximum_patch_ink_fraction
            ):
                predicted.append("?")
                positions.append(
                    PositionDecision(
                        index=index,
                        claim=claimed_digit,
                        predicted="?",
                        state=AlignmentStatus.INDETERMINATE.value,
                        top_score=0.0,
                        claim_score=0.0,
                        top_margin=0.0,
                        mismatch_delta=0.0,
                        ink_fraction=ink_fraction,
                    )
                )
                continue
            scores = self._digit_scores(patch)
            ranking = sorted(
                ((score, digit) for digit, score in scores.items()), reverse=True
            )
            top_score, top_digit = ranking[0]
            top_margin = top_score - ranking[1][0]
            claim_score = scores[claimed_digit]
            mismatch_delta = top_score - claim_score
            if (
                top_digit == claimed_digit
                and top_score >= self.thresholds.aligned_absolute
                and top_margin >= self.thresholds.aligned_margin
            ):
                state = AlignmentStatus.ALIGNED.value
            elif (
                top_digit != claimed_digit
                and top_score >= self.thresholds.mismatch_absolute
                and mismatch_delta >= self.thresholds.mismatch_delta
                and top_margin >= self.thresholds.mismatch_margin
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
                    ink_fraction=ink_fraction,
                )
            )

        states = [position.state for position in positions]
        if all(state == AlignmentStatus.ALIGNED.value for state in states):
            status = AlignmentStatus.ALIGNED
        elif (
            states.count("MISMATCH_CANDIDATE") == 1
            and states.count(AlignmentStatus.ALIGNED.value) == len(states) - 1
        ):
            status = AlignmentStatus.MISALIGNED
        else:
            status = AlignmentStatus.INDETERMINATE
        predicted_text = "".join(predicted)
        payload: dict[str, object] = {
            "schema": "ocr-pixel-digit-alignment-v4-decision/1",
            "status": status.value,
            "claim": claim,
            "predicted": predicted_text,
            "positions": [asdict(position) for position in positions],
            "cuts": list(cuts),
            "image_sha256": image_hash,
            "configuration_sha256": self.configuration_sha256,
        }
        return AlignmentDecision(
            status=status,
            claim=claim,
            predicted=predicted_text,
            positions=tuple(positions),
            cuts=cuts,
            image_sha256=image_hash,
            configuration_sha256=self.configuration_sha256,
            decision_sha256=sha256_payload(payload),
        )
