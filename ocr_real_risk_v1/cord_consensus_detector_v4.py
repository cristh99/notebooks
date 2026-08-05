"""Post-outcome CORD development laboratory for OCR consensus detector v4.

CORD is development-only after the terminal digit-forest-v3 validation. This
module may diagnose and select rules on opened CORD data, but it can never
issue an external certificate or production decision. At inference, candidate
construction uses only full-image Tesseract outputs. Expert geometry and truth
are used exclusively to score the predeclared detector configurations.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import shutil
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output

from .cord_natural_holdout import (
    DATASET_REVISION,
    SHARD_SPECS,
    crop_box,
    image_bytes_from_row,
    iter_parquet_rows,
    load_bound_candidate,
    parse_ground_truth,
    receipt_identity,
    select_numeric_annotation,
    sha256_path,
    verify_hash_manifest,
)
from .core import canonical_json, sha256_bytes, sha256_file
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .numeric_digit_forest import infer_claim
from .sroie_natural_holdout import (
    eligibility,
    match_ocr_claim,
    overlap_metrics,
    stable_payload,
    verify_stable_payload,
)

REPORT_SCHEMA = "ocr-cord-consensus-detector-v4-shard/1"
AGGREGATE_SCHEMA = "ocr-cord-consensus-detector-v4-development/1"
STATUS = "POST_OUTCOME_CORD_DEVELOPMENT_ONLY"
PSM_MODES = (3, 4, 6, 11, 12)
CROP_GUARD_PSM = 7
OCR_TIMEOUT_SECONDS = 90
ALPHA_PER_LEG = 0.0125
TARGET_REDUCTION = 10.0
MINIMUM_COVERAGE = 0.25
COUNTERFACTUAL_MAXIMUM_RISK = 0.01
_NON_DIGIT_RE = re.compile(r"\D+")
_PUNCTUATION_ONLY_RE = re.compile(r"^[\s.,:;/'\-]+$")

PSM_SETS: dict[str, tuple[int, ...]] = {
    "core": (3, 6, 11),
    "layout": (3, 4, 6),
    "sparse": (3, 11, 12),
    "broad": PSM_MODES,
}
GUARD_MODES = ("none", "psm7_any", "psm7_both")


def canonical_digits(value: object) -> str:
    return _NON_DIGIT_RE.sub("", str(value or ""))


def configuration_grid() -> list[dict[str, Any]]:
    configurations: list[dict[str, Any]] = []
    for set_name, psms in PSM_SETS.items():
        for minimum_votes in (1, 2):
            for reject_equal_length_conflict in (False, True):
                for guard_mode in GUARD_MODES:
                    identifier = (
                        f"{set_name}-v{minimum_votes}-"
                        f"{'noconflict' if reject_equal_length_conflict else 'conflict-ok'}-"
                        f"{guard_mode}"
                    )
                    configurations.append(
                        {
                            "id": identifier,
                            "psm_set": set_name,
                            "psms": list(psms),
                            "minimum_distinct_psm_votes": minimum_votes,
                            "reject_equal_length_conflict": (
                                reject_equal_length_conflict
                            ),
                            "guard_mode": guard_mode,
                            "uses_truth_for_candidate_construction": False,
                            "uses_annotation_bbox_for_candidate_construction": False,
                        }
                    )
    return configurations


def _finite_box(
    image: Image.Image,
    left: object,
    top: object,
    width: object,
    height: object,
) -> list[int] | None:
    try:
        x0 = float(left)
        y0 = float(top)
        x1 = x0 + float(width)
        y1 = y0 + float(height)
    except (TypeError, ValueError):
        return None
    values = (x0, y0, x1, y1)
    if not all(math.isfinite(value) for value in values):
        return None
    clipped = (
        max(0.0, x0),
        max(0.0, y0),
        min(float(image.width), x1),
        min(float(image.height), y1),
    )
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        return None
    return [
        int(math.floor(clipped[0])),
        int(math.floor(clipped[1])),
        int(math.ceil(clipped[2])),
        int(math.ceil(clipped[3])),
    ]


def _vertical_overlap_ratio(
    first: Sequence[float], second: Sequence[float]
) -> float:
    overlap = max(
        0.0,
        min(float(first[3]), float(second[3]))
        - max(float(first[1]), float(second[1])),
    )
    minimum_height = max(
        1e-9,
        min(
            float(first[3]) - float(first[1]),
            float(second[3]) - float(second[1]),
        ),
    )
    return overlap / minimum_height


def _window_is_contiguous(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> bool:
    previous_box = previous["bbox"]
    current_box = current["bbox"]
    if _vertical_overlap_ratio(previous_box, current_box) < 0.40:
        return False
    gap = float(current_box[0]) - float(previous_box[2])
    reference_height = max(
        float(previous_box[3]) - float(previous_box[1]),
        float(current_box[3]) - float(current_box[1]),
    )
    return gap <= max(25.0, reference_height * 1.5)


def _union_box(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    return [
        min(int(row["bbox"][0]) for row in rows),
        min(int(row["bbox"][1]) for row in rows),
        max(int(row["bbox"][2]) for row in rows),
        max(int(row["bbox"][3]) for row in rows),
    ]


def _candidate_windows(
    line_rows: Sequence[Mapping[str, Any]], psm: int
) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, tuple[int, int, int, int]], dict[str, Any]] = {}
    for start in range(len(line_rows)):
        if not canonical_digits(line_rows[start]["text"]):
            continue
        window: list[Mapping[str, Any]] = []
        for stop in range(start, min(len(line_rows), start + 4)):
            row = line_rows[stop]
            text = str(row["text"] or "").strip()
            if stop > start and not _window_is_contiguous(line_rows[stop - 1], row):
                break
            if not canonical_digits(text) and not _PUNCTUATION_ONLY_RE.fullmatch(text):
                break
            window.append(row)
            digits = canonical_digits("".join(str(item["text"]) for item in window))
            if not digits or len(digits) > 16:
                continue
            numeric_confidences = [
                float(item["confidence"])
                for item in window
                if canonical_digits(item["text"])
            ]
            confidence = (
                statistics.fmean(numeric_confidences)
                if numeric_confidences
                else -1.0
            )
            bbox = _union_box(window)
            height = max(1, bbox[3] - bbox[1])
            if bbox[2] - bbox[0] > height * 20:
                continue
            key = (digits, tuple(bbox))
            candidate = {
                "psm": psm,
                "text": "".join(str(item["text"]) for item in window),
                "digits": digits,
                "bbox": bbox,
                "confidence": confidence,
                "word_count": sum(
                    bool(canonical_digits(item["text"])) for item in window
                ),
            }
            previous = candidates.get(key)
            if previous is None or (
                confidence,
                -candidate["word_count"],
                candidate["text"],
            ) > (
                float(previous["confidence"]),
                -int(previous["word_count"]),
                str(previous["text"]),
            ):
                candidates[key] = candidate
    return sorted(
        candidates.values(),
        key=lambda row: (
            int(row["bbox"][1]),
            int(row["bbox"][0]),
            int(row["bbox"][3]),
            int(row["bbox"][2]),
            str(row["digits"]),
        ),
    )


def tesseract_numeric_candidates(
    image: Image.Image, psm: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if psm not in PSM_MODES:
        raise ValueError(f"unsupported PSM: {psm}")
    os.environ["OMP_THREAD_LIMIT"] = "1"
    started = time.perf_counter()
    try:
        data = pytesseract.image_to_data(
            image,
            lang="eng",
            config=f"--oem 1 --psm {psm}",
            output_type=Output.DICT,
            timeout=OCR_TIMEOUT_SECONDS,
        )
        timeout = False
    except RuntimeError as exc:
        if "timeout" not in str(exc).lower():
            raise
        data = {"text": []}
        timeout = True
    elapsed = time.perf_counter() - started
    lines: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    invalid_boxes = 0
    for index, raw_text in enumerate(data.get("text") or []):
        text = str(raw_text or "").strip()
        if not text:
            continue
        bbox = _finite_box(
            image,
            data.get("left", [])[index],
            data.get("top", [])[index],
            data.get("width", [])[index],
            data.get("height", [])[index],
        )
        if bbox is None:
            invalid_boxes += 1
            continue
        try:
            confidence = float(data.get("conf", [])[index])
            line_id = (
                int(data.get("block_num", [])[index]),
                int(data.get("par_num", [])[index]),
                int(data.get("line_num", [])[index]),
            )
            word_num = int(data.get("word_num", [])[index])
        except (IndexError, TypeError, ValueError):
            invalid_boxes += 1
            continue
        lines[line_id].append(
            {
                "text": text,
                "bbox": bbox,
                "confidence": confidence,
                "word_num": word_num,
            }
        )
    candidates: list[dict[str, Any]] = []
    for line_id in sorted(lines):
        rows = sorted(
            lines[line_id],
            key=lambda row: (
                int(row["word_num"]),
                int(row["bbox"][0]),
                str(row["text"]),
            ),
        )
        candidates.extend(_candidate_windows(rows, psm))
    unique: dict[tuple[int, str, tuple[int, int, int, int]], dict[str, Any]] = {}
    for candidate in candidates:
        key = (
            psm,
            str(candidate["digits"]),
            tuple(int(value) for value in candidate["bbox"]),
        )
        previous = unique.get(key)
        if previous is None or float(candidate["confidence"]) > float(
            previous["confidence"]
        ):
            unique[key] = candidate
    output = sorted(
        unique.values(),
        key=lambda row: (
            int(row["bbox"][1]),
            int(row["bbox"][0]),
            str(row["digits"]),
            -float(row["confidence"]),
        ),
    )
    return output, {
        "psm": psm,
        "wall_seconds": elapsed,
        "numeric_candidates": len(output),
        "invalid_boxes_filtered": invalid_boxes,
        "timeout": timeout,
    }


def _containment_ratio(
    first: Sequence[float], second: Sequence[float]
) -> float:
    x0 = max(float(first[0]), float(second[0]))
    y0 = max(float(first[1]), float(second[1]))
    x1 = min(float(first[2]), float(second[2]))
    y1 = min(float(first[3]), float(second[3]))
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    first_area = max(
        1e-9,
        (float(first[2]) - float(first[0]))
        * (float(first[3]) - float(first[1])),
    )
    second_area = max(
        1e-9,
        (float(second[2]) - float(second[0]))
        * (float(second[3]) - float(second[1])),
    )
    return intersection / min(first_area, second_area)


def _median_box(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    return [
        int(round(statistics.median(float(row["bbox"][index]) for row in rows)))
        for index in range(4)
    ]


def _cluster_compatibility(
    first: Sequence[float], second: Sequence[float]
) -> float:
    iou, _, _, distance = overlap_metrics(first, second)
    containment = _containment_ratio(first, second)
    vertical = _vertical_overlap_ratio(first, second)
    first_width = max(1.0, float(first[2]) - float(first[0]))
    second_width = max(1.0, float(second[2]) - float(second[0]))
    normalized_distance = distance / max(first_width, second_width)
    if vertical < 0.40:
        return -1.0
    if iou < 0.25 and containment < 0.55:
        return -1.0
    if normalized_distance > 0.75:
        return -1.0
    return max(iou, containment) - 0.05 * normalized_distance


def cluster_candidates(
    candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    ordered = sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda row: (
            int(row["bbox"][1]),
            int(row["bbox"][0]),
            int(row["psm"]),
            str(row["digits"]),
            tuple(int(value) for value in row["bbox"]),
        ),
    )
    for candidate in ordered:
        ranked: list[tuple[float, int]] = []
        for index, cluster in enumerate(clusters):
            score = _cluster_compatibility(candidate["bbox"], cluster["bbox"])
            if score >= 0:
                ranked.append((score, index))
        if not ranked:
            clusters.append({"bbox": list(candidate["bbox"]), "members": [candidate]})
            continue
        ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        selected = clusters[ranked[0][1]]
        selected["members"].append(candidate)
        selected["bbox"] = _median_box(selected["members"])
    clusters.sort(
        key=lambda cluster: (
            int(cluster["bbox"][1]),
            int(cluster["bbox"][0]),
            int(cluster["bbox"][3]),
            int(cluster["bbox"][2]),
        )
    )
    return clusters


def resolve_cluster(
    cluster: Mapping[str, Any], configuration: Mapping[str, Any]
) -> dict[str, Any] | None:
    allowed = {int(value) for value in configuration["psms"]}
    by_digits: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for raw_member in cluster["members"]:
        member = dict(raw_member)
        psm = int(member["psm"])
        if psm not in allowed:
            continue
        digits = str(member["digits"])
        previous = by_digits[digits].get(psm)
        if previous is None or (
            float(member["confidence"]),
            -int(member["word_count"]),
            tuple(int(value) for value in member["bbox"]),
        ) > (
            float(previous["confidence"]),
            -int(previous["word_count"]),
            tuple(int(value) for value in previous["bbox"]),
        ):
            by_digits[digits][psm] = member
    if not by_digits:
        return None
    ranking: list[tuple[int, float, str]] = []
    for digits, psm_rows in by_digits.items():
        ranking.append(
            (
                len(psm_rows),
                statistics.fmean(
                    float(row["confidence"]) for row in psm_rows.values()
                ),
                digits,
            )
        )
    ranking.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    votes, confidence, winner = ranking[0]
    if votes < int(configuration["minimum_distinct_psm_votes"]):
        return None
    equal_length_conflicts = sorted(
        digits
        for digits in by_digits
        if digits != winner and len(digits) == len(winner)
    )
    if (
        bool(configuration["reject_equal_length_conflict"])
        and equal_length_conflicts
    ):
        return None
    winner_rows = list(by_digits[winner].values())
    bbox = _median_box(winner_rows)
    return {
        "text": winner,
        "digits": winner,
        "bbox": bbox,
        "confidence": confidence,
        "distinct_psm_votes": votes,
        "voting_psms": sorted(by_digits[winner]),
        "equal_length_conflicts": equal_length_conflicts,
        "members": winner_rows,
    }


def resolved_tokens(
    clusters: Sequence[Mapping[str, Any]], configuration: Mapping[str, Any]
) -> list[dict[str, Any]]:
    output = []
    for cluster in clusters:
        resolved = resolve_cluster(cluster, configuration)
        if resolved is not None:
            output.append(resolved)
    return output


def _guard_image(image: Image.Image, *, autocontrast: bool) -> Image.Image:
    gray = image.convert("L")
    scale = max(2, min(6, round(96 / max(gray.height, 1))))
    resized = gray.resize(
        (max(2, gray.width * scale), max(2, gray.height * scale)),
        Image.Resampling.LANCZOS,
    )
    if autocontrast:
        resized = ImageOps.autocontrast(resized, cutoff=1)
    return ImageOps.expand(resized, border=12, fill=255)


def crop_guard_readings(image: Image.Image) -> dict[str, Any]:
    readings: dict[str, dict[str, Any]] = {}
    total_seconds = 0.0
    for name, autocontrast in (("gray", False), ("autocontrast", True)):
        source = _guard_image(image, autocontrast=autocontrast)
        started = time.perf_counter()
        try:
            raw = pytesseract.image_to_string(
                source,
                lang="eng",
                config=(
                    f"--oem 1 --psm {CROP_GUARD_PSM} "
                    "-c tessedit_char_whitelist=0123456789., "
                    "-c classify_bln_numeric_mode=1"
                ),
                timeout=15,
            )
            timeout = False
        except RuntimeError as exc:
            if "timeout" not in str(exc).lower():
                raise
            raw = ""
            timeout = True
        elapsed = time.perf_counter() - started
        total_seconds += elapsed
        readings[name] = {
            "raw": raw.strip(),
            "digits": canonical_digits(raw),
            "timeout": timeout,
            "wall_seconds": elapsed,
        }
    return {"readings": readings, "wall_seconds": total_seconds}


def guard_accepts(
    guard: Mapping[str, Any], claim: str, mode: str
) -> bool:
    if mode == "none":
        return True
    readings = [
        str(row.get("digits") or "")
        for row in guard.get("readings", {}).values()
    ]
    if mode == "psm7_any":
        return claim in readings
    if mode == "psm7_both":
        return bool(readings) and all(value == claim for value in readings)
    raise ValueError(f"unknown guard mode: {mode}")


def _empty_metrics() -> dict[str, Any]:
    return {
        "selected": 0,
        "detector_matches": 0,
        "eligible": 0,
        "baseline_errors": 0,
        "forest_accepted": 0,
        "final_accepted": 0,
        "accepted_correct": 0,
        "natural_false_accepts": 0,
        "counterfactual_false_accepts": 0,
        "reasons": {},
    }


def _finalize_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(metrics)
    selected = int(result["selected"])
    eligible = int(result["eligible"])
    accepted = int(result["final_accepted"])
    result["coverage_of_selected"] = accepted / selected if selected else 0.0
    result["coverage_of_eligible"] = accepted / eligible if eligible else 0.0
    result["reasons"] = dict(sorted(result.get("reasons", {}).items()))
    return result


def _evaluate_configuration_on_row(
    *,
    image: Image.Image,
    truth_bbox: Sequence[int],
    truth: str,
    counterfactual: str,
    clusters: Sequence[Mapping[str, Any]],
    configuration: Mapping[str, Any],
    model: Any,
    threshold: float,
    inference_cache: dict[tuple[tuple[int, int, int, int], str], dict[str, Any]],
) -> dict[str, Any]:
    tokens = resolved_tokens(clusters, configuration)
    matched = match_ocr_claim(truth_bbox, tokens)
    claim, eligible, reason = eligibility(truth, matched)
    if not eligible:
        return {
            "matched": matched,
            "claim": claim,
            "eligible": False,
            "reason": reason,
            "baseline_error": False,
            "forest_accepted": False,
            "final_accepted": False,
            "natural_false_accept": False,
            "counterfactual_false_accept": False,
            "prediction": "",
            "minimum_mean_probability": None,
            "guard": None,
        }
    box = crop_box(image, matched["bbox"], margin=2)
    cache_key = (tuple(int(value) for value in box), claim)
    cached = inference_cache.get(cache_key)
    if cached is None:
        crop = image.crop(box)
        started = time.perf_counter()
        forest = infer_claim(model, crop, claim, threshold=threshold)
        forest_seconds = time.perf_counter() - started
        guard = crop_guard_readings(crop)
        cached = {
            "crop_box": list(box),
            "forest": forest,
            "forest_seconds": forest_seconds,
            "guard": guard,
        }
        inference_cache[cache_key] = cached
    forest = cached["forest"]
    prediction = str(forest.get("prediction") or "")
    minimum_probability = float(
        forest.get("minimum_mean_probability") or 0.0
    )
    forest_accepted = bool(
        prediction == claim and minimum_probability >= threshold
    )
    final_accepted = bool(
        forest_accepted
        and guard_accepts(cached["guard"], claim, str(configuration["guard_mode"]))
    )
    counterfactual_accepted = bool(
        prediction == counterfactual
        and minimum_probability >= threshold
        and guard_accepts(
            cached["guard"],
            counterfactual,
            str(configuration["guard_mode"]),
        )
    )
    return {
        "matched": matched,
        "claim": claim,
        "eligible": True,
        "reason": reason,
        "baseline_error": claim != truth,
        "forest_accepted": forest_accepted,
        "final_accepted": final_accepted,
        "natural_false_accept": bool(final_accepted and claim != truth),
        "counterfactual_false_accept": counterfactual_accepted,
        "prediction": prediction,
        "minimum_mean_probability": minimum_probability,
        "guard": cached["guard"],
        "crop_box": cached["crop_box"],
        "forest_seconds": cached["forest_seconds"],
    }


def evaluate_shard(
    *,
    parquet_path: Path,
    manifest_path: Path,
    candidate_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not verify_stable_payload(manifest, "manifest_sha256"):
        raise RuntimeError("CORD manifest stable hash failed")
    if sha256_path(parquet_path) != manifest["dataset"]["parquet_sha256"]:
        raise RuntimeError("CORD parquet hash mismatch")
    binding = manifest["candidate_binding"]
    candidate, model = load_bound_candidate(candidate_root, binding)
    threshold = float(candidate["inference"]["threshold"])
    if threshold != 0.25:
        raise RuntimeError("digit-forest-v3 threshold changed")
    shard_id = str(manifest["dataset"]["shard_id"])
    split = str(manifest["dataset"]["split"])
    records = {
        int(record["row_index"]): dict(record)
        for record in manifest["records"]
    }
    if len(records) != len(manifest["records"]):
        raise RuntimeError("duplicate CORD selected row index")
    configurations = configuration_grid()
    metrics: dict[str, dict[str, Any]] = {
        str(configuration["id"]): _empty_metrics()
        for configuration in configurations
    }
    reason_counters: dict[str, Counter[str]] = {
        str(configuration["id"]): Counter()
        for configuration in configurations
    }
    false_cases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    processed: set[int] = set()
    runtime_by_psm: Counter[int] = Counter()
    timeout_by_psm: Counter[int] = Counter()
    candidate_count_by_psm: Counter[int] = Counter()
    guard_seconds = 0.0
    forest_seconds = 0.0
    row_summaries: list[dict[str, Any]] = []

    for row_index, row in iter_parquet_rows(parquet_path):
        record = records.get(row_index)
        if record is None:
            continue
        processed.add(row_index)
        payload = parse_ground_truth(row.get("ground_truth"))
        key, image_id = receipt_identity(payload, split)
        if key != record["key"] or image_id != int(record["image_id"]):
            raise RuntimeError("CORD receipt identity changed")
        image_bytes = image_bytes_from_row(row)
        image_sha = sha256_bytes(image_bytes)
        if image_sha != record["image_sha256"]:
            raise RuntimeError("CORD image changed")
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGB")
        selected, _ = select_numeric_annotation(
            payload=payload,
            shard_id=shard_id,
            split=split,
            key=key,
            image_sha256=image_sha,
            image_size=image.size,
        )
        if selected is None or any(
            selected[field] != record[field]
            for field in ("truth", "bbox", "selection_rank_sha256")
        ):
            raise RuntimeError("CORD selection changed")
        all_candidates: list[dict[str, Any]] = []
        psm_runtime: dict[str, Any] = {}
        for psm in PSM_MODES:
            psm_candidates, runtime = tesseract_numeric_candidates(image, psm)
            all_candidates.extend(psm_candidates)
            runtime_by_psm[psm] += float(runtime["wall_seconds"])
            timeout_by_psm[psm] += int(bool(runtime["timeout"]))
            candidate_count_by_psm[psm] += int(runtime["numeric_candidates"])
            psm_runtime[str(psm)] = runtime
        clusters = cluster_candidates(all_candidates)
        inference_cache: dict[
            tuple[tuple[int, int, int, int], str], dict[str, Any]
        ] = {}
        row_outcomes: dict[str, dict[str, Any]] = {}
        truth = str(record["truth"])
        counterfactual = str(record["counterfactual_claim"])
        for configuration in configurations:
            identifier = str(configuration["id"])
            outcome = _evaluate_configuration_on_row(
                image=image,
                truth_bbox=record["bbox"],
                truth=truth,
                counterfactual=counterfactual,
                clusters=clusters,
                configuration=configuration,
                model=model,
                threshold=threshold,
                inference_cache=inference_cache,
            )
            row_outcomes[identifier] = {
                key: value
                for key, value in outcome.items()
                if key not in {"guard"}
            }
            current = metrics[identifier]
            current["selected"] += 1
            reason_counters[identifier][str(outcome["reason"])] += 1
            if outcome["matched"] is not None:
                current["detector_matches"] += 1
            if outcome["eligible"]:
                current["eligible"] += 1
                current["baseline_errors"] += int(outcome["baseline_error"])
                current["forest_accepted"] += int(outcome["forest_accepted"])
                current["final_accepted"] += int(outcome["final_accepted"])
                current["accepted_correct"] += int(
                    outcome["final_accepted"] and not outcome["baseline_error"]
                )
                current["natural_false_accepts"] += int(
                    outcome["natural_false_accept"]
                )
                current["counterfactual_false_accepts"] += int(
                    outcome["counterfactual_false_accept"]
                )
            if outcome["natural_false_accept"] or outcome[
                "counterfactual_false_accept"
            ]:
                false_cases[identifier].append(
                    {
                        "shard_id": shard_id,
                        "split": split,
                        "row_index": row_index,
                        "key": key,
                        "truth": truth,
                        "counterfactual": counterfactual,
                        "claim": outcome["claim"],
                        "prediction": outcome["prediction"],
                        "minimum_mean_probability": outcome[
                            "minimum_mean_probability"
                        ],
                        "natural_false_accept": outcome[
                            "natural_false_accept"
                        ],
                        "counterfactual_false_accept": outcome[
                            "counterfactual_false_accept"
                        ],
                        "matched": outcome["matched"],
                        "guard": outcome["guard"],
                    }
                )
        guard_seconds += sum(
            float(cached["guard"]["wall_seconds"])
            for cached in inference_cache.values()
        )
        forest_seconds += sum(
            float(cached["forest_seconds"])
            for cached in inference_cache.values()
        )
        row_summaries.append(
            {
                "row_index": row_index,
                "key": key,
                "truth": truth,
                "counterfactual": counterfactual,
                "image_sha256": image_sha,
                "candidate_clusters": len(clusters),
                "raw_candidates": len(all_candidates),
                "psm_runtime": psm_runtime,
                "outcomes": row_outcomes,
            }
        )
        print(
            json.dumps(
                {
                    "shard_id": shard_id,
                    "processed": len(row_summaries),
                    "selected": len(records),
                    "clusters": len(clusters),
                    "inference_variants": len(inference_cache),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if processed != set(records):
        raise RuntimeError(
            f"selected CORD rows missing: {sorted(set(records) - processed)[:10]}"
        )
    finalized_metrics = {}
    for configuration in configurations:
        identifier = str(configuration["id"])
        metrics[identifier]["reasons"] = dict(reason_counters[identifier])
        finalized_metrics[identifier] = _finalize_metrics(metrics[identifier])
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": STATUS,
        "dataset": dict(manifest["dataset"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "candidate_binding": dict(binding),
        "candidate_threshold": threshold,
        "configurations": configurations,
        "metrics": finalized_metrics,
        "false_cases": {
            key: value for key, value in sorted(false_cases.items())
        },
        "runtime": {
            "psm_wall_seconds": {
                str(key): value for key, value in sorted(runtime_by_psm.items())
            },
            "psm_timeouts": {
                str(key): value for key, value in sorted(timeout_by_psm.items())
            },
            "numeric_candidates": {
                str(key): value
                for key, value in sorted(candidate_count_by_psm.items())
            },
            "crop_guard_wall_seconds": guard_seconds,
            "forest_wall_seconds": forest_seconds,
        },
        "row_summaries": row_summaries,
        "decision": {
            "external_certificate": False,
            "production_ready": False,
            "cord_development_only": True,
            "fresh_external_corpus_required": True,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    report = stable_payload(report, "stable_payload_sha256")
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "cord_consensus_detector_v4_shard.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        f"{sha256_path(report_path)}  {report_path.name}\n",
        encoding="utf-8",
    )
    return report


def _sum_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = _empty_metrics()
    reasons: Counter[str] = Counter()
    for row in rows:
        for key in (
            "selected",
            "detector_matches",
            "eligible",
            "baseline_errors",
            "forest_accepted",
            "final_accepted",
            "accepted_correct",
            "natural_false_accepts",
            "counterfactual_false_accepts",
        ):
            total[key] += int(row[key])
        reasons.update(row.get("reasons") or {})
    total["reasons"] = dict(reasons)
    return _finalize_metrics(total)


def exact_diagnostic(metrics: Mapping[str, Any]) -> dict[str, Any]:
    selected = int(metrics["selected"])
    eligible = int(metrics["eligible"])
    baseline_false = int(metrics["baseline_errors"])
    accepted = int(metrics["final_accepted"])
    accepted_false = int(metrics["natural_false_accepts"])
    counter_false = int(metrics["counterfactual_false_accepts"])
    baseline_lower = (
        clopper_pearson_lower(
            baseline_false, eligible, ALPHA_PER_LEG
        )
        if eligible
        else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(
            accepted_false, accepted, ALPHA_PER_LEG
        )
        if accepted
        else 1.0
    )
    coverage_lower = (
        clopper_pearson_lower(accepted, selected, ALPHA_PER_LEG)
        if selected
        else 0.0
    )
    counter_upper = (
        clopper_pearson_upper(counter_false, selected, ALPHA_PER_LEG)
        if selected
        else 1.0
    )
    return {
        "baseline_lower": baseline_lower,
        "candidate_upper": candidate_upper,
        "coverage_lower": coverage_lower,
        "counterfactual_upper": counter_upper,
        "reduction_lower": (
            baseline_lower / candidate_upper
            if candidate_upper > 0
            else None
        ),
        "development_gate": bool(
            baseline_false > 0
            and accepted_false == 0
            and counter_false == 0
            and coverage_lower >= MINIMUM_COVERAGE
            and candidate_upper <= baseline_lower / TARGET_REDUCTION
            and counter_upper <= COUNTERFACTUAL_MAXIMUM_RISK
        ),
    }


def _configuration_tiebreak(configuration: Mapping[str, Any]) -> tuple[Any, ...]:
    guard_rank = {"psm7_both": 0, "psm7_any": 1, "none": 2}
    return (
        guard_rank[str(configuration["guard_mode"])],
        -int(configuration["minimum_distinct_psm_votes"]),
        not bool(configuration["reject_equal_length_conflict"]),
        len(configuration["psms"]),
        str(configuration["id"]),
    )


def aggregate_reports(
    roots: Iterable[Path], output_dir: Path
) -> dict[str, Any]:
    reports: dict[str, dict[str, Any]] = {}
    for root in sorted(roots):
        verify_hash_manifest(root)
        report = json.loads(
            (root / "cord_consensus_detector_v4_shard.json").read_text(
                encoding="utf-8"
            )
        )
        if report.get("schema") != REPORT_SCHEMA:
            raise RuntimeError(f"unexpected shard report schema: {root}")
        if not verify_stable_payload(report, "stable_payload_sha256"):
            raise RuntimeError(f"shard stable payload failed: {root}")
        shard_id = str(report["dataset"]["shard_id"])
        if shard_id in reports:
            raise RuntimeError(f"duplicate shard report: {shard_id}")
        reports[shard_id] = report
    if set(reports) != set(SHARD_SPECS):
        raise RuntimeError(
            f"requires all CORD shards: {sorted(reports)}"
        )
    configuration_by_id = {
        str(row["id"]): row
        for row in next(iter(reports.values()))["configurations"]
    }
    if set(configuration_by_id) != {
        str(row["id"]) for row in configuration_grid()
    }:
        raise RuntimeError("configuration grid changed")
    for report in reports.values():
        if canonical_json(report["configurations"]) != canonical_json(
            list(configuration_by_id.values())
        ):
            raise RuntimeError("shard configuration grids differ")
    train_shards = sorted(
        shard_id for shard_id in reports if shard_id.startswith("train-")
    )
    validation_shards = ["validation-00000-of-00001"]
    test_shards = ["test-00000-of-00001"]
    split_metrics: dict[str, dict[str, dict[str, Any]]] = {
        "train": {},
        "validation": {},
        "test": {},
        "all": {},
    }
    for identifier in sorted(configuration_by_id):
        split_metrics["train"][identifier] = _sum_metrics(
            [reports[shard]["metrics"][identifier] for shard in train_shards]
        )
        split_metrics["validation"][identifier] = _sum_metrics(
            [
                reports[shard]["metrics"][identifier]
                for shard in validation_shards
            ]
        )
        split_metrics["test"][identifier] = _sum_metrics(
            [reports[shard]["metrics"][identifier] for shard in test_shards]
        )
        split_metrics["all"][identifier] = _sum_metrics(
            [reports[shard]["metrics"][identifier] for shard in sorted(reports)]
        )
    eligible_candidates = []
    for identifier, metrics in split_metrics["train"].items():
        if (
            int(metrics["natural_false_accepts"]) == 0
            and int(metrics["counterfactual_false_accepts"]) == 0
            and int(metrics["final_accepted"]) > 0
        ):
            eligible_candidates.append(identifier)
    if not eligible_candidates:
        raise RuntimeError("no zero-failure train configuration exists")
    eligible_candidates.sort(
        key=lambda identifier: (
            -int(split_metrics["train"][identifier]["final_accepted"]),
            _configuration_tiebreak(configuration_by_id[identifier]),
        )
    )
    selected_id = eligible_candidates[0]
    selected_configuration = configuration_by_id[selected_id]
    selected_metrics = {
        split: split_metrics[split][selected_id]
        for split in ("train", "validation", "test", "all")
    }
    diagnostics = {
        split: exact_diagnostic(metrics)
        for split, metrics in selected_metrics.items()
    }
    ranked_zero_failure = []
    for identifier in eligible_candidates[:20]:
        ranked_zero_failure.append(
            {
                "configuration": configuration_by_id[identifier],
                "train": split_metrics["train"][identifier],
                "validation": split_metrics["validation"][identifier],
                "test": split_metrics["test"][identifier],
                "all": split_metrics["all"][identifier],
                "all_exact_diagnostic": exact_diagnostic(
                    split_metrics["all"][identifier]
                ),
            }
        )
    false_cases = {
        shard_id: reports[shard_id]["false_cases"].get(selected_id, [])
        for shard_id in sorted(reports)
        if reports[shard_id]["false_cases"].get(selected_id)
    }
    internal_generalization_pass = bool(
        selected_metrics["validation"]["natural_false_accepts"] == 0
        and selected_metrics["validation"]["counterfactual_false_accepts"] == 0
        and selected_metrics["test"]["natural_false_accepts"] == 0
        and selected_metrics["test"]["counterfactual_false_accepts"] == 0
    )
    result: dict[str, Any] = {
        "schema": AGGREGATE_SCHEMA,
        "status": STATUS,
        "dataset": {
            "repo": "naver-clova-ix/cord-v2",
            "revision": DATASET_REVISION,
            "role": "opened development corpus; never external validation again",
            "shards": dict(SHARD_SPECS),
        },
        "candidate_binding": dict(
            next(iter(reports.values()))["candidate_binding"]
        ),
        "selection_rule": {
            "selected_on": "four CORD train shards only",
            "constraint": (
                "zero natural and counterfactual false accepts on train, "
                "then maximum accepted count; deterministic conservative tiebreak"
            ),
            "configuration": selected_configuration,
        },
        "metrics": selected_metrics,
        "exact_diagnostics": diagnostics,
        "ranked_zero_failure_train_configurations": ranked_zero_failure,
        "selected_configuration_false_cases": false_cases,
        "decision": {
            "internal_generalization_pass": internal_generalization_pass,
            "cord_development_gate_pass": bool(
                internal_generalization_pass
                and diagnostics["all"]["development_gate"]
            ),
            "candidate_ready_for_sroie_cross_development": bool(
                internal_generalization_pass
                and selected_metrics["all"]["natural_false_accepts"] == 0
                and selected_metrics["all"][
                    "counterfactual_false_accepts"
                ]
                == 0
            ),
            "candidate_ready_to_freeze": False,
            "external_certificate": False,
            "production_ready": False,
            "fresh_external_corpus_required": True,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    result = stable_payload(result, "stable_payload_sha256")
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "cord_consensus_detector_v4_development.json"
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        f"{sha256_path(path)}  {path.name}\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--parquet", required=True, type=Path)
    evaluate.add_argument("--manifest", required=True, type=Path)
    evaluate.add_argument("--candidate-root", required=True, type=Path)
    evaluate.add_argument("--output-dir", required=True, type=Path)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("roots", nargs="+", type=Path)
    aggregate.add_argument("--output-dir", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "evaluate":
        report = evaluate_shard(
            parquet_path=args.parquet,
            manifest_path=args.manifest,
            candidate_root=args.candidate_root,
            output_dir=args.output_dir,
        )
        print(
            json.dumps(
                {
                    "dataset": report["dataset"],
                    "runtime": report["runtime"],
                    "stable_payload_sha256": report[
                        "stable_payload_sha256"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = aggregate_reports(args.roots, args.output_dir)
    print(
        json.dumps(
            {
                "selection_rule": result["selection_rule"],
                "metrics": result["metrics"],
                "exact_diagnostics": result["exact_diagnostics"],
                "decision": result["decision"],
                "stable_payload_sha256": result[
                    "stable_payload_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
