"""Geometry-only reading-order benchmark for OmniDocBench v1.6.

No OCR model, image pixels, network service, or paid API participates in the
ordering algorithms. The only inputs to the algorithms are block bounding
boxes and page dimensions.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA = "ocr-reading-order-real-v1/report/1"
DATASET_ID = "opendatalab/OmniDocBench"
ANNOTATION_FILE = "OmniDocBench.json"
PINNED_REVISION = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"
EXPECTED_ANNOTATION_SHA256 = "a45cd84b04ad8b793e775089640e6b681209abea33ead54c1828ddca35fae496"
SPLIT_RULE = "sha256(page_id)[0:8] mod 5 == 0 => holdout"

EXCLUDED_CATEGORIES = frozenset({
    "abandon",
    "chart_mask",
    "table_mask",
    "text_mask",
    "organic_chemical_formula_mask",
    "algorithm_mask",
    "unknown_mask",
    "need_mask",
})


@dataclass(frozen=True)
class Block:
    block_id: str
    order: int
    category: str
    bbox: tuple[float, float, float, float]

    @property
    def left(self) -> float:
        return self.bbox[0]

    @property
    def top(self) -> float:
        return self.bbox[1]

    @property
    def right(self) -> float:
        return self.bbox[2]

    @property
    def bottom(self) -> float:
        return self.bbox[3]

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass(frozen=True)
class Page:
    page_id: str
    width: float
    height: float
    layout: str
    domain: str
    language: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Candidate:
    name: str
    orderer: Callable[[Sequence[Block], float, float], list[Block]]
    complexity_rank: int


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bbox_from_poly(poly: Any) -> tuple[float, float, float, float]:
    if hasattr(poly, "tolist"):
        poly = poly.tolist()
    if not isinstance(poly, (list, tuple)) or not poly:
        raise ValueError("polygon must be a non-empty sequence")
    if isinstance(poly[0], (list, tuple)):
        points = [(float(point[0]), float(point[1])) for point in poly]
    else:
        flat = [float(value) for value in poly]
        if len(flat) < 4 or len(flat) % 2:
            raise ValueError("flat polygon must contain coordinate pairs")
        points = list(zip(flat[0::2], flat[1::2], strict=True))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    box = (min(xs), min(ys), max(xs), max(ys))
    if not all(math.isfinite(value) for value in box):
        raise ValueError("non-finite polygon")
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("degenerate polygon")
    return box


def page_from_raw(raw: Mapping[str, Any]) -> Page | None:
    info = raw.get("page_info") or {}
    page_id = str(info.get("image_path") or info.get("image") or "").strip()
    if not page_id:
        return None
    attrs = info.get("page_attribute") or info.get("attribute") or {}
    width = float(info.get("width") or 0)
    height = float(info.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    blocks: list[Block] = []
    for index, item in enumerate(raw.get("layout_dets") or []):
        if item.get("ignore", False):
            continue
        category = str(item.get("category_type") or item.get("category") or "")
        if not category or category in EXCLUDED_CATEGORIES:
            continue
        order = item.get("order")
        if isinstance(order, bool) or not isinstance(order, int):
            continue
        try:
            bbox = bbox_from_poly(item.get("poly") or item.get("bbox"))
        except (TypeError, ValueError):
            continue
        anno_id = item.get("anno_id", index)
        block_id = f"{page_id}::{anno_id}::{index}"
        blocks.append(Block(block_id, order, category, bbox))
    if len(blocks) < 2:
        return None
    return Page(
        page_id=page_id,
        width=width,
        height=height,
        layout=str(attrs.get("layout") or "unknown"),
        domain=str(attrs.get("data_source") or "unknown"),
        language=str(attrs.get("language") or "unknown"),
        blocks=tuple(blocks),
    )


def split_name(page_id: str) -> str:
    bucket = int(hashlib.sha256(page_id.encode("utf-8")).hexdigest()[:8], 16) % 5
    return "holdout" if bucket == 0 else "development"


def levenshtein(left: Sequence[Any], right: Sequence[Any]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, item_left in enumerate(left, start=1):
        current = [i]
        for j, item_right in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (item_left != item_right),
                )
            )
        previous = current
    return previous[-1]


def order_metrics(page: Page, predicted: Sequence[Block]) -> dict[str, float | int | bool]:
    if len(predicted) != len(page.blocks):
        raise ValueError("prediction denominator mismatch")
    expected_ids = {block.block_id for block in page.blocks}
    predicted_ids = [block.block_id for block in predicted]
    if len(predicted_ids) != len(set(predicted_ids)) or set(predicted_ids) != expected_ids:
        raise ValueError("prediction is not a permutation of page blocks")

    gt_values = sorted(block.order for block in page.blocks)
    pred_values = [block.order for block in predicted]
    read_order_edit = levenshtein(gt_values, pred_values) / max(len(gt_values), len(pred_values), 1)

    correct = 0
    comparable = 0
    for left_index, left in enumerate(predicted):
        for right in predicted[left_index + 1 :]:
            if left.order == right.order:
                continue
            comparable += 1
            if left.order < right.order:
                correct += 1
    pairwise_accuracy = correct / comparable if comparable else 1.0
    return {
        "blocks": len(page.blocks),
        "comparable_pairs": comparable,
        "read_order_edit": read_order_edit,
        "pairwise_accuracy": pairwise_accuracy,
        "exact": pred_values == gt_values,
    }


def _yx(nodes: Sequence[Block], _page_width: float, _page_height: float) -> list[Block]:
    return sorted(nodes, key=lambda node: (node.top, node.left, node.bottom, node.right, node.block_id))


def _center_yx(nodes: Sequence[Block], _page_width: float, _page_height: float) -> list[Block]:
    return sorted(nodes, key=lambda node: (node.center_y, node.center_x, node.top, node.left, node.block_id))


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _row_bands(nodes: Sequence[Block], _page_width: float, _page_height: float) -> list[Block]:
    if len(nodes) <= 1:
        return list(nodes)
    ordered = sorted(nodes, key=lambda node: (node.top, node.left, node.block_id))
    rows: list[list[Block]] = []
    for node in ordered:
        best_index: int | None = None
        best_score = 0.0
        for index, row in enumerate(rows):
            row_top = min(item.top for item in row)
            row_bottom = max(item.bottom for item in row)
            overlap = _overlap(node.top, node.bottom, row_top, row_bottom)
            score = overlap / max(min(node.height, row_bottom - row_top), 1e-9)
            if score >= 0.35 and score > best_score:
                best_index = index
                best_score = score
        if best_index is None:
            rows.append([node])
        else:
            rows[best_index].append(node)
    rows.sort(key=lambda row: (min(item.top for item in row), min(item.left for item in row)))
    result: list[Block] = []
    for row in rows:
        result.extend(sorted(row, key=lambda node: (node.left, node.top, node.block_id)))
    return result


def _projection_gaps(nodes: Sequence[Block], axis: str) -> list[tuple[float, float]]:
    if axis == "x":
        intervals = sorted((node.left, node.right) for node in nodes)
    elif axis == "y":
        intervals = sorted((node.top, node.bottom) for node in nodes)
    else:
        raise ValueError("axis must be x or y")
    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [
        ((merged[index][1] + merged[index + 1][0]) / 2.0, merged[index + 1][0] - merged[index][1])
        for index in range(len(merged) - 1)
        if merged[index + 1][0] > merged[index][1]
    ]


def _xy_cut(
    nodes: Sequence[Block],
    page_width: float,
    page_height: float,
    *,
    min_gap_ratio: float,
    horizontal_bias: float,
) -> list[Block]:
    if len(nodes) <= 1:
        return list(nodes)
    left = min(node.left for node in nodes)
    right = max(node.right for node in nodes)
    top = min(node.top for node in nodes)
    bottom = max(node.bottom for node in nodes)
    width = max(right - left, page_width * 1e-9)
    height = max(bottom - top, page_height * 1e-9)
    x_gaps = _projection_gaps(nodes, "x")
    y_gaps = _projection_gaps(nodes, "y")
    best_x = max(x_gaps, key=lambda item: item[1], default=None)
    best_y = max(y_gaps, key=lambda item: item[1], default=None)
    x_score = 0.0 if best_x is None else best_x[1] / width
    y_score = 0.0 if best_y is None else best_y[1] / height * horizontal_bias
    if max(x_score, y_score) < min_gap_ratio:
        return _row_bands(nodes, page_width, page_height)
    if y_score >= x_score and best_y is not None:
        cut = best_y[0]
        first = [node for node in nodes if node.center_y < cut]
        second = [node for node in nodes if node.center_y >= cut]
    elif best_x is not None:
        cut = best_x[0]
        first = [node for node in nodes if node.center_x < cut]
        second = [node for node in nodes if node.center_x >= cut]
    else:
        return _row_bands(nodes, page_width, page_height)
    if not first or not second:
        return _row_bands(nodes, page_width, page_height)
    return _xy_cut(
        first,
        page_width,
        page_height,
        min_gap_ratio=min_gap_ratio,
        horizontal_bias=horizontal_bias,
    ) + _xy_cut(
        second,
        page_width,
        page_height,
        min_gap_ratio=min_gap_ratio,
        horizontal_bias=horizontal_bias,
    )


def _make_xycut(min_gap_ratio: float, horizontal_bias: float) -> Callable[[Sequence[Block], float, float], list[Block]]:
    def orderer(nodes: Sequence[Block], page_width: float, page_height: float) -> list[Block]:
        return _xy_cut(
            nodes,
            page_width,
            page_height,
            min_gap_ratio=min_gap_ratio,
            horizontal_bias=horizontal_bias,
        )

    return orderer


def _column_sort(nodes: Sequence[Block], page_width: float, page_height: float) -> list[Block]:
    if len(nodes) <= 1:
        return list(nodes)
    gaps = _projection_gaps(nodes, "x")
    if not gaps:
        return _row_bands(nodes, page_width, page_height)
    cut, gap = max(gaps, key=lambda item: item[1])
    extent = max(max(node.right for node in nodes) - min(node.left for node in nodes), 1e-9)
    if gap / extent < 0.025:
        return _row_bands(nodes, page_width, page_height)
    left = [node for node in nodes if node.center_x < cut]
    right = [node for node in nodes if node.center_x >= cut]
    if not left or not right:
        return _row_bands(nodes, page_width, page_height)
    return _column_sort(left, page_width, page_height) + _column_sort(right, page_width, page_height)


def _spanning_bands(
    nodes: Sequence[Block],
    page_width: float,
    page_height: float,
    *,
    wide_ratio: float,
) -> list[Block]:
    if len(nodes) <= 1:
        return list(nodes)
    wide = sorted(
        [node for node in nodes if node.width / max(page_width, 1e-9) >= wide_ratio],
        key=lambda node: (node.center_y, node.left, node.block_id),
    )
    if not wide:
        return _column_sort(nodes, page_width, page_height)
    wide_ids = {node.block_id for node in wide}
    narrow = [node for node in nodes if node.block_id not in wide_ids]
    result: list[Block] = []
    remaining = narrow[:]
    for separator in wide:
        before = [node for node in remaining if node.center_y < separator.center_y]
        before_ids = {node.block_id for node in before}
        remaining = [node for node in remaining if node.block_id not in before_ids]
        result.extend(_column_sort(before, page_width, page_height))
        result.append(separator)
    result.extend(_column_sort(remaining, page_width, page_height))
    return result


def _make_spanning(wide_ratio: float) -> Callable[[Sequence[Block], float, float], list[Block]]:
    def orderer(nodes: Sequence[Block], page_width: float, page_height: float) -> list[Block]:
        return _spanning_bands(
            nodes,
            page_width,
            page_height,
            wide_ratio=wide_ratio,
        )

    return orderer


def _precedence_cmp(left: Block, right: Block) -> int:
    x_overlap = _overlap(left.left, left.right, right.left, right.right)
    y_overlap = _overlap(left.top, left.bottom, right.top, right.bottom)
    x_ratio = x_overlap / max(min(left.width, right.width), 1e-9)
    y_ratio = y_overlap / max(min(left.height, right.height), 1e-9)
    if x_ratio >= 0.20:
        key_left = (left.top, left.left, left.block_id)
        key_right = (right.top, right.left, right.block_id)
    elif y_ratio >= 0.20:
        key_left = (left.left, left.top, left.block_id)
        key_right = (right.left, right.top, right.block_id)
    else:
        key_left = (left.top, left.left, left.block_id)
        key_right = (right.top, right.left, right.block_id)
    return -1 if key_left < key_right else (1 if key_left > key_right else 0)


def _precedence(nodes: Sequence[Block], _page_width: float, _page_height: float) -> list[Block]:
    return sorted(nodes, key=cmp_to_key(_precedence_cmp))


CANDIDATES: tuple[Candidate, ...] = (
    Candidate("yx_baseline", _yx, 0),
    Candidate("center_yx", _center_yx, 1),
    Candidate("row_bands", _row_bands, 2),
    Candidate("xycut_loose", _make_xycut(0.005, 0.60), 3),
    Candidate("xycut_balanced", _make_xycut(0.015, 0.70), 4),
    Candidate("xycut_conservative", _make_xycut(0.030, 0.85), 5),
    Candidate("spanning_bands_055", _make_spanning(0.55), 6),
    Candidate("spanning_bands_070", _make_spanning(0.70), 7),
    Candidate("precedence", _precedence, 8),
)


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / max(len(items), 1)


def summarize_page_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "pages": len(rows),
        "blocks": sum(int(row["blocks"]) for row in rows),
        "comparable_pairs": sum(int(row["comparable_pairs"]) for row in rows),
        "mean_read_order_edit": _mean(float(row["read_order_edit"]) for row in rows),
        "mean_pairwise_accuracy": _mean(float(row["pairwise_accuracy"]) for row in rows),
        "exact_page_rate": _mean(float(bool(row["exact"])) for row in rows),
    }


def evaluate_candidate(candidate: Candidate, pages: Sequence[Page]) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for page in pages:
        predicted = candidate.orderer(page.blocks, page.width, page.height)
        metrics = order_metrics(page, predicted)
        rows.append(
            {
                "page_id": page.page_id,
                "layout": page.layout,
                "domain": page.domain,
                "language": page.language,
                **metrics,
            }
        )
    elapsed = time.perf_counter() - started
    return summarize_page_metrics(rows), rows, elapsed


def selection_key(candidate: Candidate, summary: Mapping[str, Any]) -> tuple[float, float, float, int, str]:
    return (
        float(summary["mean_read_order_edit"]),
        -float(summary["mean_pairwise_accuracy"]),
        -float(summary["exact_page_rate"]),
        candidate.complexity_rank,
        candidate.name,
    )


def grouped_summary(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {name: summarize_page_metrics(group) for name, group in sorted(groups.items())}


def solver_receipt() -> dict[str, Any]:
    """Proof-carrying receipt of the finite robust decision used for this run.

    Utilities are declared research value under the current hard constraints;
    they are not empirical OCR performance claims.
    """
    worlds = (
        "reading_order_bottleneck",
        "segmentation_bottleneck",
        "recognizer_bottleneck",
        "serialization_metric_mismatch",
    )
    actions = {
        "geometry_only_order_canary": (10, 9, 7, 10),
        "tesseract_box_order_canary": (8, 9, 6, 7),
        "open_layout_model_benchmark": (7, 10, 7, 6),
        "train_recognizer": (2, 3, 10, 1),
    }
    best_by_world = [max(values[index] for values in actions.values()) for index in range(len(worlds))]
    regrets = {
        action: [best_by_world[index] - value for index, value in enumerate(values)]
        for action, values in actions.items()
    }
    max_regret = {action: max(values) for action, values in regrets.items()}
    selected = min(max_regret, key=lambda action: (max_regret[action], action))
    problem_ir = {
        "schema": "logic-power-problem-ir/1",
        "problem_id": "OCR-REAL-READING-ORDER-001",
        "states": list(worlds),
        "initial_belief": list(worlds),
        "goal": "identify the minimum zero-cost capability that materially improves real document reading order",
        "conditions": [
            {"name": "zero_spend", "kind": "BUDGET", "expression": "external_spend_usd == 0"},
            {"name": "no_gcloud", "kind": "HARD_CONSTRAINT", "expression": "gcloud_used == false"},
            {"name": "planner_only", "kind": "SAFETY_INVARIANT", "expression": "Logic Power is not imported by OCR runtime"},
            {"name": "real_holdout", "kind": "EVIDENCE_REQUIREMENT", "expression": "sealed real pages plus deterministic replay"},
            {"name": "current_observation", "kind": "FACT", "expression": "region recall is high while serialized text accuracy remains low"},
        ],
        "actions": list(actions),
        "experiments": list(actions),
        "agents": ["ocr_research_controller"],
        "horizon": "STATIC",
        "uncertainty": "UNKNOWN",
        "model_status": "KNOWN",
        "objective": "minimize worst-case regret before adding OCR runtime cost",
        "capabilities": ["logic_exact", "robust_minimax_regret", "github", "huggingface", "motherduck", "wolfram"],
        "verifiers": ["python_reference_verifier", "sha256", "github_actions"],
        "search_budget": {"rollouts": 0, "max_depth": 0, "time_ms": 0, "memory_mb": 0},
        "solution_concept": "finite minimax regret",
    }
    payload = {
        "problem_ir": problem_ir,
        "worlds": list(worlds),
        "utilities": {action: list(values) for action, values in sorted(actions.items())},
        "regrets": {action: values for action, values in sorted(regrets.items())},
        "max_regret": {action: max_regret[action] for action in sorted(max_regret)},
        "selected_experiment": selected,
        "rejected": [action for action in sorted(actions) if action != selected],
    }
    return {**payload, "receipt_sha256": sha256_bytes(canonical_json(payload).encode("utf-8"))}


def decision_from_metrics(selected: Mapping[str, Any], baseline: Mapping[str, Any], by_layout: Mapping[str, Any]) -> dict[str, Any]:
    selected_edit = float(selected["mean_read_order_edit"])
    baseline_edit = float(baseline["mean_read_order_edit"])
    relative_improvement = (baseline_edit - selected_edit) / baseline_edit if baseline_edit > 0 else 0.0
    worst_layout_edit = max(
        (float(summary["mean_read_order_edit"]) for summary in by_layout.values()),
        default=1.0,
    )
    promote = (
        selected_edit <= 0.10
        and float(selected["mean_pairwise_accuracy"]) >= 0.95
        and float(selected["exact_page_rate"]) >= 0.60
        and worst_layout_edit <= 0.20
    )
    partial = relative_improvement >= 0.20 and selected_edit < baseline_edit
    if promote:
        verdict = "PROMOTE_GEOMETRY_ORDER_KERNEL"
        next_experiment = "apply frozen winner to Tesseract-detected boxes on the same sealed page identities"
    elif partial:
        verdict = "GEOMETRY_IS_PARTIAL"
        next_experiment = "test geometry plus block semantics; do not add a recognizer"
    else:
        verdict = "REJECT_GEOMETRY_ONLY"
        next_experiment = "benchmark a lightweight open layout-order model before any training"
    return {
        "verdict": verdict,
        "selected_vs_yx_relative_edit_improvement": relative_improvement,
        "worst_layout_mean_edit": worst_layout_edit,
        "next_experiment": next_experiment,
        "automatic_production_change": False,
    }
