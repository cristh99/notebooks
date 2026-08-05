"""Evaluate the frozen semantic numeric resolver on annotated natural receipts.

Annotations are used only after decisions are made. The runtime path consumes
only the image and baseline OCR geometry. This script is suitable for a sealed,
receipt-disjoint canary when the stem manifest is fixed before annotations are
opened.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ["OMP_THREAD_LIMIT"] = "1"

from PIL import Image
from scipy.stats import beta

from .semantic_numeric_resolver_v4 import (
    OCRToken,
    ResolutionAction,
    canonical_ascii_digits,
    detect_semantic_flags,
    run_two_probe_crop_resolver,
    tesseract_page_tokens,
)

SCHEMA = "ocr-semantic-numeric-resolver-v4-canary/1"
_NUMERIC_PATTERNS = (
    re.compile(r"^[+-]?[0-9]+$"),
    re.compile(r"^[+-]?[0-9]+[.,][0-9]+$"),
    re.compile(r"^[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?$"),
    re.compile(r"^[+-]?[0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?$"),
    re.compile(r"^[0-9]+(?:/[0-9]+)+$"),
    re.compile(r"^[0-9]+(?:-[0-9]+)+$"),
)
_YEAR = re.compile(r"^(?:19|20)[0-9]{2}$")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def numeric_truth(text: str) -> str | None:
    value = str(text or "").strip().upper()
    value = re.sub(r"^(?:RM|MYR|USD|US\$|\$)\s*:?\s*", "", value)
    value = value.strip(" \t\r\n:;#()[]{}*")
    if not value or not any(pattern.fullmatch(value) for pattern in _NUMERIC_PATTERNS):
        return None
    digits = canonical_ascii_digits(value)
    if not 4 <= len(digits) <= 12:
        return None
    if _YEAR.fullmatch(digits):
        return None
    if len(digits) >= 6 and len(set(digits)) == 1:
        return None
    return digits


def parse_annotations(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 9:
                continue
            try:
                coordinates = [float(value) for value in row[:8]]
            except ValueError:
                continue
            text = ",".join(row[8:]).strip()
            truth = numeric_truth(text)
            if truth is None:
                continue
            xs = coordinates[0::2]
            ys = coordinates[1::2]
            output.append({"text": text, "truth": truth, "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    return output


def overlap_metrics(first: Sequence[float], second: Sequence[float]) -> tuple[float, float, float, float]:
    ax0, ay0, ax1, ay1 = map(float, first)
    bx0, by0, bx1, by1 = map(float, second)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1e-9, (bx1 - bx0) * (by1 - by0))
    union = area_a + area_b - intersection
    center_a = ((ax0 + ax1) / 2.0, (ay0 + ay1) / 2.0)
    center_b = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
    distance = math.hypot(center_a[0] - center_b[0], center_a[1] - center_b[1])
    return intersection / union, intersection / area_a, intersection / area_b, distance


def match_token(truth_bbox: Sequence[float], tokens: Sequence[OCRToken]) -> tuple[OCRToken, dict[str, float]] | None:
    tx0, ty0, tx1, ty1 = map(float, truth_bbox)
    truth_center = ((tx0 + tx1) / 2.0, (ty0 + ty1) / 2.0)
    ranked: list[tuple[float, float, str, OCRToken, dict[str, float]]] = []
    for token in tokens:
        if not token.digits:
            continue
        iou, truth_coverage, token_coverage, distance = overlap_metrics(truth_bbox, token.bbox)
        bx0, by0, bx1, by1 = token.bbox
        contains_center = bx0 <= truth_center[0] <= bx1 and by0 <= truth_center[1] <= by1
        if truth_coverage < 0.35 and not contains_center:
            continue
        score = 3.0 * truth_coverage + token_coverage + 0.5 * iou - 0.001 * distance
        ranked.append((score, token.confidence, token.digits, token, {"iou": iou, "truth_coverage": truth_coverage, "token_coverage": token_coverage, "center_distance": distance, "score": score}))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return ranked[0][3], ranked[0][4]


def clopper_pearson_lower(errors: int, total: int, alpha: float = 0.05) -> float:
    if errors == 0:
        return 0.0
    return float(beta.ppf(alpha, errors, total - errors + 1))


def clopper_pearson_upper(errors: int, total: int, alpha: float = 0.05) -> float:
    if errors == total:
        return 1.0
    return float(beta.ppf(1.0 - alpha, errors + 1, total - errors))


def tesseract_version() -> str:
    result = subprocess.run(["tesseract", "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return result.stdout.splitlines()[0].strip() if result.stdout else "unknown"


def evaluate(root: Path, stems: Sequence[str], *, status: str) -> dict[str, Any]:
    page_records: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    baseline_seconds = 0.0
    semantic_seconds = 0.0
    crop_wall_seconds = 0.0

    for stem in stems:
        image_path = root / f"{stem}.jpg"
        annotation_path = root / f"{stem}.txt"
        if not image_path.exists() or not annotation_path.exists():
            raise FileNotFoundError(f"missing image/annotation pair for {stem}")
        with Image.open(image_path) as opened:
            page = opened.convert("RGB")
        tokens, page_seconds = tesseract_page_tokens(page, psm=3)
        baseline_seconds += page_seconds
        semantic_started = time.perf_counter()
        flags = detect_semantic_flags(tokens)
        semantic_seconds += time.perf_counter() - semantic_started
        token_by_index = {token.index: token for token in tokens}
        resolutions: dict[int, dict[str, Any]] = {}
        for flag in flags:
            token = token_by_index[flag.token_index]
            crop_started = time.perf_counter()
            decision, crop_box = run_two_probe_crop_resolver(page, token)
            crop_wall_seconds += time.perf_counter() - crop_started
            resolutions[token.index] = {
                "flag": {"token_index": flag.token_index, "reasons": [reason.value for reason in flag.reasons]},
                "crop_box": list(crop_box),
                "decision": {
                    "action": decision.action.value,
                    "reason_code": decision.reason_code,
                    "baseline": decision.baseline,
                    "output": decision.output,
                    "decision_sha256": decision.decision_sha256,
                    "evidence": [asdict(item) for item in decision.evidence],
                },
            }

        annotations = parse_annotations(annotation_path)
        eligible = 0
        for annotation in annotations:
            match = match_token(annotation["bbox"], tokens)
            if match is None:
                continue
            token, geometry = match
            if len(token.digits) != len(annotation["truth"]) or geometry["truth_coverage"] < 0.50:
                continue
            eligible += 1
            resolution = resolutions.get(token.index)
            accepted = True
            final_text = token.text
            if resolution is not None:
                action = ResolutionAction(resolution["decision"]["action"])
                if action == ResolutionAction.REPLACE:
                    final_text = str(resolution["decision"]["output"])
                elif action == ResolutionAction.QUARANTINE:
                    accepted = False
            final_digits = canonical_ascii_digits(final_text)
            observations.append({
                "page": stem,
                "truth": annotation["truth"],
                "annotation_text": annotation["text"],
                "truth_bbox": annotation["bbox"],
                "baseline": {"token_index": token.index, "text": token.text, "digits": token.digits, "confidence": token.confidence, "bbox": list(token.bbox), "correct": token.digits == annotation["truth"]},
                "geometry": geometry,
                "semantic_resolution": resolution,
                "final": {"accepted": accepted, "text": final_text, "digits": final_digits, "correct": accepted and final_digits == annotation["truth"]},
            })
        page_records.append({
            "stem": stem,
            "image_sha256": sha256_path(image_path),
            "annotation_sha256": sha256_path(annotation_path),
            "image_size": list(page.size),
            "numeric_annotations_in_scope": len(annotations),
            "eligible_claims": eligible,
            "baseline_seconds": page_seconds,
            "semantic_flags": len(flags),
            "resolutions": list(resolutions.values()),
        })

    baseline_errors = sum(not row["baseline"]["correct"] for row in observations)
    accepted_rows = [row for row in observations if row["final"]["accepted"]]
    final_errors = sum(not row["final"]["correct"] for row in accepted_rows)
    replacements = [row for row in observations if row["semantic_resolution"] is not None and row["semantic_resolution"]["decision"]["action"] == ResolutionAction.REPLACE.value]
    false_replacements = sum(row["baseline"]["correct"] for row in replacements)
    corrected_errors = sum(not row["baseline"]["correct"] and row["final"]["correct"] for row in replacements)
    total = len(observations)
    baseline_lower = clopper_pearson_lower(baseline_errors, total)
    final_upper = clopper_pearson_upper(final_errors, len(accepted_rows))
    conservative_reduction = baseline_lower / final_upper if final_upper else None
    candidate_seconds = baseline_seconds + semantic_seconds + crop_wall_seconds

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": status,
        "source": {"corpus": "ICDAR2019 SROIE Task 1 natural receipt images", "stems": list(stems), "pages": len(stems), "annotations_used_at_inference": False, "annotations_used_for_post_decision_evaluation": True},
        "protocol": {
            "baseline": "Tesseract 5, eng, OEM 1, PSM 3, RGB page serialized losslessly",
            "semantic_triggers": ["singleton decimal Hamming-1 from a value repeated on >=2 distinct lines", "quantity-one row with exactly two decimal amounts that disagree by one digit"],
            "crop_probes": ["original grayscale PSM 7", "autocontrast 2x PSM 13"],
            "replacement_rule": "replace only when both distinct crop probes agree on the same equal-length alternative; otherwise keep confirmed baseline or quarantine",
            "numeric_scope": "self-contained 4-12 ASCII-digit expression after declared separator normalization; standalone years and repeated-digit junk excluded",
        },
        "environment": {"python": platform.python_version(), "tesseract": tesseract_version(), "omp_thread_limit": 1, "external_spend_usd": 0.0, "gcloud_used": False, "gpu_used": False, "paid_api_used": False, "github_actions_used": False, "production_modified": False},
        "metrics": {
            "eligible_claims": total,
            "baseline_errors": baseline_errors,
            "baseline_observed_error_rate": baseline_errors / total if total else None,
            "semantic_flags": sum(page["semantic_flags"] for page in page_records),
            "replacements": len(replacements),
            "corrected_errors": corrected_errors,
            "false_replacements": false_replacements,
            "quarantined": total - len(accepted_rows),
            "accepted": len(accepted_rows),
            "accepted_coverage": len(accepted_rows) / total if total else None,
            "final_errors": final_errors,
            "final_observed_error_rate": final_errors / len(accepted_rows) if accepted_rows else None,
            "observed_baseline_errors_eliminated_fraction": (baseline_errors - final_errors) / baseline_errors if baseline_errors else None,
            "one_sided_95pct_baseline_error_lower": baseline_lower,
            "one_sided_95pct_final_error_upper": final_upper,
            "conservative_error_reduction_lower": conservative_reduction,
            "statistical_10x_certified": bool(conservative_reduction is not None and conservative_reduction >= 10.0),
        },
        "timing": {"baseline_full_page_seconds": baseline_seconds, "semantic_trigger_seconds": semantic_seconds, "crop_resolver_wall_seconds": crop_wall_seconds, "candidate_total_seconds": candidate_seconds, "candidate_to_baseline_runtime_ratio": candidate_seconds / baseline_seconds if baseline_seconds else None, "speed_10x_certified": False},
        "decision": {"production_promotion": False, "quality_10x_status": "BLOCKED_STATISTICALLY", "speed_10x_status": "NOT_ACHIEVED_BY_THIS_RESOLVER", "next_gate": "freeze candidate and execute on a receipt-disjoint manifest selected before annotations are fetched"},
        "pages": page_records,
        "observations": observations,
    }
    report["stable_payload_sha256"] = hashlib.sha256(canonical_json(report)).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stems", nargs="+", required=True)
    parser.add_argument("--status", default="DEVELOPMENT_ONLY")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.root, args.stems, status=args.status)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "metrics": report["metrics"], "timing": report["timing"], "stable_payload_sha256": report["stable_payload_sha256"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
