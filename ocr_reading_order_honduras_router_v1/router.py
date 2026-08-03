"""Frozen zero-model router between y/x and XY-cut reading orders.

This router was specified after PR #33 and before any document in the new
holdout was acquired. It uses geometry only and never sees text, document type,
ground truth, Logic Power, or OCR confidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ocr_reading_order_real_v1.core import Block, CANDIDATES

HEADER_MAX_CENTER_Y = 0.35
FOOTER_MIN_CENTER_Y = 0.55
BODY_MIN_COLUMN_GAP = 0.08
BODY_MIN_VERTICAL_OVERLAP = 0.20
WIDE_SPANNING_RATIO = 0.70


@dataclass(frozen=True)
class RouterDecision:
    selected: str
    reason: str
    baseline_order: tuple[str, ...]
    geometry_order: tuple[str, ...]
    selected_order: tuple[str, ...]
    disagreement_blocks: tuple[str, ...]
    features: Mapping[str, Any]


def _candidate(name: str):
    return next(item for item in CANDIDATES if item.name == name)


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
        raise ValueError("router requires at least two blocks")
    return result


def _orders(
    blocks: Sequence[Mapping[str, Any]], page_width: float, page_height: float
) -> tuple[list[Block], list[Block]]:
    geometry = _geometry_blocks(blocks)
    baseline = _candidate("yx_baseline").orderer(geometry, page_width, page_height)
    xycut = _candidate("xycut_loose").orderer(geometry, page_width, page_height)
    return baseline, xycut


def disagreement_block_ids(
    baseline: Sequence[Block], geometry: Sequence[Block]
) -> tuple[str, ...]:
    baseline_position = {block.block_id: index for index, block in enumerate(baseline)}
    geometry_position = {block.block_id: index for index, block in enumerate(geometry)}
    if set(baseline_position) != set(geometry_position):
        raise ValueError("candidate orders have different denominators")
    changed: set[str] = set()
    ids = sorted(baseline_position)
    for left_index, left in enumerate(ids):
        for right in ids[left_index + 1 :]:
            baseline_relation = baseline_position[left] < baseline_position[right]
            geometry_relation = geometry_position[left] < geometry_position[right]
            if baseline_relation != geometry_relation:
                changed.add(left)
                changed.add(right)
    return tuple(sorted(changed))


def _vertical_overlap_ratio(left: Sequence[Block], right: Sequence[Block], page_height: float) -> float:
    left_top = min(block.top for block in left)
    left_bottom = max(block.bottom for block in left)
    right_top = min(block.top for block in right)
    right_bottom = max(block.bottom for block in right)
    overlap = max(0.0, min(left_bottom, right_bottom) - max(left_top, right_top))
    return overlap / max(page_height, 1e-9)


def _strong_body_columns(
    changed: Sequence[Block], all_blocks: Sequence[Block], page_width: float, page_height: float
) -> dict[str, Any]:
    ordered = sorted(changed, key=lambda block: block.center_x)
    best: dict[str, Any] = {
        "strong": False,
        "gap_ratio": 0.0,
        "vertical_overlap_ratio": 0.0,
        "spanning_block_present": False,
    }
    for index in range(1, len(ordered)):
        left_group = ordered[:index]
        right_group = ordered[index:]
        gap = min(block.left for block in right_group) - max(block.right for block in left_group)
        gap_ratio = gap / max(page_width, 1e-9)
        if gap_ratio <= best["gap_ratio"]:
            continue
        vertical_overlap = _vertical_overlap_ratio(left_group, right_group, page_height)
        region_top = min(block.top for block in changed)
        region_bottom = max(block.bottom for block in changed)
        cut_x = (
            max(block.right for block in left_group)
            + min(block.left for block in right_group)
        ) / 2.0
        spanning = any(
            block.width / max(page_width, 1e-9) >= WIDE_SPANNING_RATIO
            and block.top <= region_bottom
            and block.bottom >= region_top
            and block.left < cut_x < block.right
            for block in all_blocks
        )
        best = {
            "strong": (
                gap_ratio >= BODY_MIN_COLUMN_GAP
                and vertical_overlap >= BODY_MIN_VERTICAL_OVERLAP
                and not spanning
            ),
            "gap_ratio": gap_ratio,
            "vertical_overlap_ratio": vertical_overlap,
            "spanning_block_present": spanning,
        }
    return best


def route(
    blocks: Sequence[Mapping[str, Any]], page_width: float, page_height: float
) -> RouterDecision:
    if page_width <= 0 or page_height <= 0:
        raise ValueError("page dimensions must be positive")
    baseline, geometry = _orders(blocks, page_width, page_height)
    baseline_ids = tuple(block.block_id for block in baseline)
    geometry_ids = tuple(block.block_id for block in geometry)
    changed_ids = disagreement_block_ids(baseline, geometry)
    all_by_id = {block.block_id: block for block in baseline}

    if not changed_ids:
        return RouterDecision(
            selected="baseline",
            reason="CANDIDATES_IDENTICAL",
            baseline_order=baseline_ids,
            geometry_order=geometry_ids,
            selected_order=baseline_ids,
            disagreement_blocks=(),
            features={"disagreement_count": 0},
        )

    changed = [all_by_id[block_id] for block_id in changed_ids]
    normalized_centers = [block.center_y / page_height for block in changed]
    min_center_y = min(normalized_centers)
    max_center_y = max(normalized_centers)
    body_columns = _strong_body_columns(changed, list(all_by_id.values()), page_width, page_height)
    features: dict[str, Any] = {
        "disagreement_count": len(changed_ids),
        "min_changed_center_y": min_center_y,
        "max_changed_center_y": max_center_y,
        "body_columns": body_columns,
        "thresholds": {
            "header_max_center_y": HEADER_MAX_CENTER_Y,
            "footer_min_center_y": FOOTER_MIN_CENTER_Y,
            "body_min_column_gap": BODY_MIN_COLUMN_GAP,
            "body_min_vertical_overlap": BODY_MIN_VERTICAL_OVERLAP,
            "wide_spanning_ratio": WIDE_SPANNING_RATIO,
        },
    }

    if min_center_y <= HEADER_MAX_CENTER_Y:
        selected = "baseline"
        reason = "HEADER_METADATA_PROTECTION"
    elif min_center_y >= FOOTER_MIN_CENTER_Y:
        selected = "geometry"
        reason = "LOWER_PARALLEL_REGION"
    elif body_columns["strong"]:
        selected = "geometry"
        reason = "STRONG_BODY_COLUMNS"
    else:
        selected = "baseline"
        reason = "INSUFFICIENT_BODY_COLUMN_EVIDENCE"

    selected_order = geometry_ids if selected == "geometry" else baseline_ids
    return RouterDecision(
        selected=selected,
        reason=reason,
        baseline_order=baseline_ids,
        geometry_order=geometry_ids,
        selected_order=selected_order,
        disagreement_blocks=changed_ids,
        features=features,
    )
