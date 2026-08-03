"""Frozen geometry-only region composer.

The composer preserves the top band in row-major order and independently
orders the middle and lower bands with a wide-anchor column algorithm. It sees
only block boxes and page dimensions. It never sees text, OCR confidence,
document type, annotations, Logic Power, or prior outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ocr_reading_order_real_v1.core import Block, _row_bands, _spanning_bands

FROZEN_HEADER_FRACTION = 0.30
FROZEN_LOWER_SPLIT = 0.65
FROZEN_WIDE_RATIO = 0.70


@dataclass(frozen=True)
class ComposerDecision:
    order: tuple[str, ...]
    top_order: tuple[str, ...]
    middle_order: tuple[str, ...]
    lower_order: tuple[str, ...]
    features: Mapping[str, Any]


def _geometry_blocks(blocks: Sequence[Mapping[str, Any]]) -> list[Block]:
    result: list[Block] = []
    seen: set[str] = set()
    for item in blocks:
        block_id = str(item["block_id"])
        if block_id in seen:
            raise ValueError(f"duplicate block ID: {block_id}")
        seen.add(block_id)
        bbox = tuple(float(value) for value in item["bbox"])
        if len(bbox) != 4 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError(f"invalid bbox: {block_id}")
        result.append(Block(block_id, 0, "tesseract_block", bbox))
    if len(result) < 2:
        raise ValueError("composer requires at least two blocks")
    return result


def compose_with_parameters(
    blocks: Sequence[Mapping[str, Any]],
    page_width: float,
    page_height: float,
    *,
    header_fraction: float,
    lower_split: float,
    wide_ratio: float = FROZEN_WIDE_RATIO,
) -> ComposerDecision:
    if page_width <= 0 or page_height <= 0:
        raise ValueError("page dimensions must be positive")
    if not 0.0 <= header_fraction < lower_split <= 1.0:
        raise ValueError("invalid vertical band thresholds")
    if not 0.0 < wide_ratio <= 1.0:
        raise ValueError("invalid wide ratio")

    geometry = _geometry_blocks(blocks)
    top = [block for block in geometry if block.center_y / page_height <= header_fraction]
    middle = [
        block
        for block in geometry
        if header_fraction < block.center_y / page_height < lower_split
    ]
    lower = [block for block in geometry if block.center_y / page_height >= lower_split]

    top_order = _row_bands(top, page_width, page_height)
    middle_order = _spanning_bands(
        middle,
        page_width,
        page_height,
        wide_ratio=wide_ratio,
    )
    lower_order = _spanning_bands(
        lower,
        page_width,
        page_height,
        wide_ratio=wide_ratio,
    )
    combined = [*top_order, *middle_order, *lower_order]
    expected = {block.block_id for block in geometry}
    observed = [block.block_id for block in combined]
    if len(observed) != len(expected) or set(observed) != expected:
        raise AssertionError("composer output is not a block permutation")

    return ComposerDecision(
        order=tuple(observed),
        top_order=tuple(block.block_id for block in top_order),
        middle_order=tuple(block.block_id for block in middle_order),
        lower_order=tuple(block.block_id for block in lower_order),
        features={
            "header_fraction": header_fraction,
            "lower_split": lower_split,
            "wide_ratio": wide_ratio,
            "top_blocks": len(top),
            "middle_blocks": len(middle),
            "lower_blocks": len(lower),
        },
    )


def compose(
    blocks: Sequence[Mapping[str, Any]],
    page_width: float,
    page_height: float,
) -> ComposerDecision:
    return compose_with_parameters(
        blocks,
        page_width,
        page_height,
        header_fraction=FROZEN_HEADER_FRACTION,
        lower_split=FROZEN_LOWER_SPLIT,
        wide_ratio=FROZEN_WIDE_RATIO,
    )
