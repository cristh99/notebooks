"""Geometry for isolating one native PDF word before OCR.

The generic evaluator uses proportional padding intended for arbitrary words.
For numeric risk measurement that padding can absorb currency prefixes or an
adjacent table cell, turning crop contamination into a mislabeled OCR error.
This module keeps the entire declared native word box while applying only a
small, fixed raster margin.
"""
from __future__ import annotations

import math
from typing import Sequence

HORIZONTAL_PAD_PX = 3
VERTICAL_PAD_PX = 6


def isolated_native_word_box(
    bbox_pt: Sequence[float],
    page_size_pt: tuple[float, float],
    image_size_px: tuple[int, int],
    *,
    horizontal_pad_px: int = HORIZONTAL_PAD_PX,
    vertical_pad_px: int = VERTICAL_PAD_PX,
) -> tuple[int, int, int, int]:
    """Return a clipped raster box containing one native word and fixed pads."""
    if len(bbox_pt) != 4:
        raise ValueError("bbox_pt must contain four coordinates")
    if horizontal_pad_px < 0 or vertical_pad_px < 0:
        raise ValueError("padding must be non-negative")
    page_width, page_height = (float(value) for value in page_size_pt)
    image_width, image_height = (int(value) for value in image_size_px)
    if page_width <= 0 or page_height <= 0:
        raise ValueError("page dimensions must be positive")
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")
    x0, y0, x1, y1 = (float(value) for value in bbox_pt)
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise ValueError("bbox coordinates must be finite")
    if x1 <= x0 or y1 <= y0:
        raise ValueError("bbox must have positive area")
    scale_x = image_width / page_width
    scale_y = image_height / page_height
    box = (
        max(0, math.floor(x0 * scale_x) - horizontal_pad_px),
        max(0, math.floor(y0 * scale_y) - vertical_pad_px),
        min(image_width, math.ceil(x1 * scale_x) + horizontal_pad_px),
        min(image_height, math.ceil(y1 * scale_y) + vertical_pad_px),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("isolated crop is empty")
    return box
