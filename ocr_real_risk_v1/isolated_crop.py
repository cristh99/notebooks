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

from PIL import Image

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


def recrop_from_artifact(
    padded_crop: Image.Image,
    padded_box_px: Sequence[int],
    bbox_pt: Sequence[float],
    page_size_pt: tuple[float, float],
    page_image_size_px: tuple[int, int],
    *,
    horizontal_pad_px: int = HORIZONTAL_PAD_PX,
    vertical_pad_px: int = VERTICAL_PAD_PX,
) -> tuple[Image.Image, tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Recover the isolated word crop from a previously retained padded crop."""
    if len(padded_box_px) != 4:
        raise ValueError("padded_box_px must contain four coordinates")
    global_box = isolated_native_word_box(
        bbox_pt,
        page_size_pt,
        page_image_size_px,
        horizontal_pad_px=horizontal_pad_px,
        vertical_pad_px=vertical_pad_px,
    )
    padded_left, padded_top, padded_right, padded_bottom = (
        int(value) for value in padded_box_px
    )
    if padded_right <= padded_left or padded_bottom <= padded_top:
        raise ValueError("retained padded box is empty")
    relative_box = (
        global_box[0] - padded_left,
        global_box[1] - padded_top,
        global_box[2] - padded_left,
        global_box[3] - padded_top,
    )
    if (
        relative_box[0] < 0
        or relative_box[1] < 0
        or relative_box[2] > padded_crop.width
        or relative_box[3] > padded_crop.height
    ):
        raise ValueError("isolated word box is not contained in retained crop")
    if relative_box[2] <= relative_box[0] or relative_box[3] <= relative_box[1]:
        raise ValueError("relative isolated crop is empty")
    return padded_crop.crop(relative_box), global_box, relative_box
