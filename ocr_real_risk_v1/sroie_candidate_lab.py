"""Post-outcome development laboratory for the numeric verifier.

SROIE is no longer an untouched validation set. This module may use its labels
only to design a new candidate. It never emits a certificate and every output
states that a different untouched corpus is required for validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

from .core import canonical_json, p95, sha256_bytes
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .pixel_digit_alignment import AlignmentStatus, PixelDigitAligner, _ink, _segment
from .sroie_natural_holdout import verify_stable_payload

SCHEMA = "ocr-numeric-consensus-candidate-lab/1"
ALPHA_PER_LEG = 0.0125
PIXEL_VIEW_NAMES = ("original", "autocontrast2", "clahe2", "otsu2")
OCR_VARIANTS = (
    ("original_psm7", "original", 7),
    ("autocontrast2_psm7", "autocontrast2", 7),
    ("clahe2_psm8", "clahe2", 8),
    ("otsu2_psm13", "otsu2", 13),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hash_manifest(root: Path) -> None:
    manifest = root / "SHA256SUMS.txt"
    if not manifest.exists():
        raise RuntimeError(f"missing SHA256SUMS.txt in {root}")
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = raw.split("  ", 1)
        target = root / relative
        if _sha256(target) != expected:
            raise RuntimeError(f"hash mismatch: {target}")


def _digits(value: object) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _resize2(image: Image.Image) -> Image.Image:
    return image.resize(
        (max(2, image.width * 2), max(2, image.height * 2)),
        Image.Resampling.LANCZOS,
    )


def deterministic_views(image: Image.Image) -> dict[str, Image.Image]:
    gray = image.convert("L")
    array = np.array(gray)
    enlarged = _resize2(gray)
    contrast = _resize2(ImageOps.autocontrast(gray, cutoff=1))
    clahe_array = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(array)
    clahe = _resize2(Image.fromarray(clahe_array))
    _, otsu_array = cv2.threshold(
        array,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    otsu = _resize2(Image.fromarray(otsu_array))
    return {
        "original": gray,
        "autocontrast2": contrast,
        "clahe2": clahe,
        "otsu2": otsu,
    }


def tesseract_crop_claim(image: Image.Image, psm: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        text = pytesseract.image_to_string(
            image,
            lang="eng",
            config=f"--oem 1 --psm {psm}",
            timeout=15,
        )
        timeout = False
    except RuntimeError as exc:
        if "timeout" not in str(exc).lower():
            raise
        text = ""
        timeout = True
    return {
        "text": text.strip(),
        "digits": _digits(text),
        "psm": psm,
        "timeout": timeout,
        "wall_seconds": time.perf_counter() - started,
    }


def pixel_payload(aligner: PixelDigitAligner, image: Image.Image, claim: str) -> dict[str, Any]:
    return aligner.align(image, claim).to_data(include_positions=True)


def patch_topology(image: Image.Image, length: int) -> list[dict[str, Any]]:
    patches, cuts = _segment(_ink(image), length)
    output: list[dict[str, Any]] = []
    for index, patch in enumerate(patches):
        if patch.size == 0:
            output.append(
                {
                    "index": index,
                    "cut": [int(cuts[index]), int(cuts[index + 1])],
                    "height": 0,
                    "width": 0,
                    "foreground_ratio": 0.0,
                    "components": 0,
                    "holes": 0,
                }
            )
            continue
        foreground = (patch > 0).astype(np.uint8)
        components, _, stats, _ = cv2.connectedComponentsWithStats(foreground, 8)
        component_count = sum(
            int(stats[component, cv2.CC_STAT_AREA]) >= max(2, int(patch.size * 0.002))
            for component in range(1, components)
        )
        contours, hierarchy = cv2.findContours(
            (foreground * 255).astype(np.uint8),
            cv2.RETR_CCOMP,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        holes = 0
        if hierarchy is not None:
            holes = sum(int(row[3]) >= 0 for row in hierarchy[0])
        output.append(
            {
                "index": index,
                "cut": [int(cuts[index]), int(cuts[index + 1])],
                "height": int(patch.shape[0]),
                "width": int(patch.shape[1]),
                "foreground_ratio": float(foreground.mean()),
                "components": int(component_count),
                "holes": int(holes),
            }
        )
    return output


def claim_features(
    claim: str,
    pixel: Mapping[str, Mapping[str, Any]],
    crop_ocr: Mapping[str, Mapping[str, Any]],
    *,
    full_page_confidence: float,
) -> dict[str, Any]:
    decisions = list(pixel.values())
    aligned_views = sum(row["status"] == AlignmentStatus.ALIGNED.value for row in decisions)
    misaligned_views = sum(row["status"] == AlignmentStatus.MISALIGNED.value for row in decisions)
    predicted_views = sum(row["predicted"] == claim for row in decisions)
    per_position_votes: list[int] = []
    per_position_claim_scores: list[float] = []
    per_position_top_margins: list[float] = []
    for index in range(len(claim)):
        positions = [row["positions"][index] for row in decisions]
        per_position_votes.append(
            sum(position["predicted"] == claim[index] for position in positions)
        )
        per_position_claim_scores.append(
            float(statistics.median(float(position["claim_score"]) for position in positions))
        )
        per_position_top_margins.append(
            float(statistics.median(float(position["top_margin"]) for position in positions))
        )
    outputs = [str(row["digits"]) for row in crop_ocr.values()]
    exact_ocr_votes = sum(output == claim for output in outputs)
    equal_length_conflicts = sorted(
        {
            output
            for output in outputs
            if output and len(output) == len(claim) and output != claim
        }
    )
    return {
        "aligned_views": int(aligned_views),
        "misaligned_views": int(misaligned_views),
        "predicted_views": int(predicted_views),
        "minimum_position_vote": int(min(per_position_votes) if per_position_votes else 0),
        "minimum_position_median_claim_score": float(
            min(per_position_claim_scores) if per_position_claim_scores else 0.0
        ),
        "minimum_position_median_top_margin": float(
            min(per_position_top_margins) if per_position_top_margins else 0.0
        ),
        "exact_ocr_votes": int(exact_ocr_votes),
        "ocr_nonempty_outputs": int(sum(bool(output) for output in outputs)),
        "ocr_equal_length_conflicts": equal_length_conflicts,
        "full_page_confidence": float(full_page_confidence),
        "original_pixel_status": str(pixel["original"]["status"]),
        "original_pixel_prediction": str(pixel["original"]["predicted"]),
    }


def base_accept(features: Mapping[str, Any], rule: Mapping[str, Any]) -> bool:
    strict = bool(
        rule["retain_original_strict"]
        and features["original_pixel_status"] == AlignmentStatus.ALIGNED.value
    )
    extension = bool(
        features["misaligned_views"] == 0
        and features["predicted_views"] >= rule["predicted_views_min"]
        and features["minimum_position_vote"] >= rule["position_vote_min"]
        and features["minimum_position_median_claim_score"]
        >= rule["position_median_claim_score_min"]
        and features["exact_ocr_votes"] >= rule["ocr_exact_votes_min"]
        and not features["ocr_equal_length_conflicts"]
        and features["full_page_confidence"] >= rule["full_page_confidence_min"]
    )
    return strict or extension


def rule_grid() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for retain_original_strict in (False, True):
        for predicted_views_min in (3, 4):
            for position_vote_min in (3, 4):
                for score_min in (0.56, 0.60, 0.64):
                    for ocr_votes_min in (2, 3, 4):
                        for confidence_min in (70.0, 80.0, 90.0):
                            rules.append(
                                {
                                    "retain_original_strict": retain_original_strict,
                                    "predicted_views_min": predicted_views_min,
                                    "position_vote_min": position_vote_min,
                                    "position_median_claim_score_min": score_min,
                                    "ocr_exact_votes_min": ocr_votes_min,
                                    "full_page_confidence_min": confidence_min,
                                }
                            )
    return rules


def metric_payload(records: Sequence[Mapping[str, Any]], rule: Mapping[str, Any]) -> dict[str, Any]:
    natural_accepted = [row for row in records if base_accept(row["natural_features"], rule)]
    natural_false = sum(not row["claim_correct"] for row in natural_accepted)
    counterfactual_accepted = [
        row for row in records if base_accept(row["counterfactual_features"], rule)
    ]
    counterfactual_false = len(counterfactual_accepted)
    selected = len(records)
    coverage = len(natural_accepted) / selected if selected else 0.0
    coverage_lower = (
        clopper_pearson_lower(len(natural_accepted), selected, ALPHA_PER_LEG)
        if selected
        else 0.0
    )
    natural_upper = (
        clopper_pearson_upper(natural_false, len(natural_accepted), ALPHA_PER_LEG)
        if natural_accepted
        else 1.0
    )
    counterfactual_upper = (
        clopper_pearson_upper(counterfactual_false, selected, ALPHA_PER_LEG)
        if selected
        else 1.0
    )
    return {
        "selected": selected,
        "accepted": len(natural_accepted),
        "accepted_correct": len(natural_accepted) - natural_false,
        "natural_false_accepts": natural_false,
        "observed_coverage": coverage,
        "simultaneous_95pct_coverage_lower": coverage_lower,
        "simultaneous_95pct_natural_risk_upper": natural_upper,
        "counterfactual_false_accepts": counterfactual_false,
        "simultaneous_95pct_counterfactual_upper": counterfactual_upper,
    }


def rule_complexity(rule: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(bool(rule["retain_original_strict"])),
        -int(rule["ocr_exact_votes_min"]),
        -int(rule["predicted_views_min"]),
        -int(rule["position_vote_min"]),
        -float(rule["position_median_claim_score_min"]),
        -float(rule["full_page_confidence_min"]),
    )


def select_rule(train_records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evaluated: list[dict[str, Any]] = []
    for rule in rule_grid():
        metrics = metric_payload(train_records, rule)
        evaluated.append({"rule": rule, "metrics": metrics})
    safe = [
        row
        for row in evaluated
        if row["metrics"]["natural_false_accepts"] == 0
        and row["metrics"]["counterfactual_false_accepts"] == 0
    ]
    pool = safe or evaluated
    pool.sort(
        key=lambda row: (
            row["metrics"]["accepted"],
            row["metrics"]["simultaneous_95pct_coverage_lower"],
            -row["metrics"]["simultaneous_95pct_natural_risk_upper"],
            tuple(-value if isinstance(value, (int, float)) else value for value in rule_complexity(row["rule"])),
        ),
        reverse=True,
    )
    selected = pool[0]
    leaderboard = sorted(
        evaluated,
        key=lambda row: (
            row["metrics"]["natural_false_accepts"] == 0,
            row["metrics"]["counterfactual_false_accepts"] == 0,
            row["metrics"]["accepted"],
            row["metrics"]["simultaneous_95pct_coverage_lower"],
        ),
        reverse=True,
    )[:40]
    return selected, leaderboard


def load_records(roots: Iterable[Path], output_dir: Path) -> list[dict[str, Any]]:
    aligner = PixelDigitAligner()
    records: list[dict[str, Any]] = []
    diagnostic_dir = output_dir / "diagnostic-crops"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    for root in roots:
        _verify_hash_manifest(root)
        report = json.loads((root / "split_report.json").read_text(encoding="utf-8"))
        if not verify_stable_payload(report, "stable_payload_sha256"):
            raise RuntimeError(f"split report stable payload mismatch: {root}")
        for observation in report["observations"]:
            if not observation["tesseract"]["eligible"]:
                continue
            claim = str(observation["tesseract"]["claim"])
            counterfactual = str(observation["counterfactual"]["claim"])
            crop_path = root / str(observation["verifier"]["crop_file"])
            if _sha256(crop_path) != observation["verifier"]["crop_sha256"]:
                raise RuntimeError(f"crop hash mismatch: {crop_path}")
            with Image.open(crop_path) as opened:
                crop = opened.convert("L")
            views = deterministic_views(crop)
            pixel_natural = {
                name: pixel_payload(aligner, views[name], claim)
                for name in PIXEL_VIEW_NAMES
            }
            pixel_counterfactual = {
                name: pixel_payload(aligner, views[name], counterfactual)
                for name in PIXEL_VIEW_NAMES
            }
            crop_ocr = {
                label: tesseract_crop_claim(views[view_name], psm)
                for label, view_name, psm in OCR_VARIANTS
            }
            confidence = float(
                (observation["tesseract"].get("matched") or {}).get("confidence") or -1.0
            )
            natural_features = claim_features(
                claim,
                pixel_natural,
                crop_ocr,
                full_page_confidence=confidence,
            )
            counterfactual_features = claim_features(
                counterfactual,
                pixel_counterfactual,
                crop_ocr,
                full_page_confidence=confidence,
            )
            records.append(
                {
                    "split": observation["split"],
                    "key": observation["key"],
                    "company_group": observation["company_group"],
                    "evidence_key": observation["evidence_key"],
                    "truth": observation["truth"],
                    "claim": claim,
                    "claim_correct": bool(observation["tesseract"]["claim_correct"]),
                    "counterfactual_claim": counterfactual,
                    "full_page_confidence": confidence,
                    "crop_file": observation["verifier"]["crop_file"],
                    "crop_sha256": observation["verifier"]["crop_sha256"],
                    "natural_features": natural_features,
                    "counterfactual_features": counterfactual_features,
                    "pixel_natural": pixel_natural,
                    "pixel_counterfactual": pixel_counterfactual,
                    "crop_ocr": crop_ocr,
                    "topology": {
                        name: patch_topology(views[name], len(claim))
                        for name in PIXEL_VIEW_NAMES
                    },
                }
            )
            if len(records) % 25 == 0:
                print(
                    json.dumps(
                        {
                            "eligible_records_processed": len(records),
                            "natural_errors": sum(not row["claim_correct"] for row in records),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
    return records


def aggregate(roots: Sequence[Path], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = load_records(roots, output_dir)
    split_counts = Counter(str(row["split"]) for row in records)
    if split_counts != {"train": 355, "test": 216}:
        raise RuntimeError(f"unexpected eligible split counts: {dict(split_counts)}")
    train_records = [row for row in records if row["split"] == "train"]
    test_records = [row for row in records if row["split"] == "test"]
    selected, leaderboard = select_rule(train_records)
    rule = selected["rule"]
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "POST_OUTCOME_DEVELOPMENT_ONLY",
        "source": {
            "dataset": "jsdnrs/ICDAR2019-SROIE",
            "sroie_outcomes_already_opened": True,
            "eligible_records": len(records),
            "train_eligible": len(train_records),
            "test_eligible": len(test_records),
            "natural_baseline_errors": sum(not row["claim_correct"] for row in records),
        },
        "views": {
            "pixel": list(PIXEL_VIEW_NAMES),
            "crop_ocr": [
                {"label": label, "view": view_name, "psm": psm}
                for label, view_name, psm in OCR_VARIANTS
            ],
        },
        "selected_rule": rule,
        "selection_objective": {
            "split": "train",
            "require_zero_observed_natural_false_accepts": True,
            "require_zero_observed_counterfactual_false_accepts": True,
            "maximize_accepted_after_constraints": True,
            "certification_claimed": False,
        },
        "metrics": {
            "train_selection": metric_payload(train_records, rule),
            "test_posthoc_check": metric_payload(test_records, rule),
            "combined_posthoc": metric_payload(records, rule),
        },
        "leaderboard": leaderboard,
        "diagnostics": {
            "natural_false_accept_keys": [
                row["key"]
                for row in records
                if base_accept(row["natural_features"], rule) and not row["claim_correct"]
            ],
            "counterfactual_false_accept_keys": [
                row["key"]
                for row in records
                if base_accept(row["counterfactual_features"], rule)
            ],
            "current_strict": {
                "accepted": sum(
                    row["natural_features"]["original_pixel_status"]
                    == AlignmentStatus.ALIGNED.value
                    for row in records
                ),
                "natural_false_accepts": sum(
                    row["natural_features"]["original_pixel_status"]
                    == AlignmentStatus.ALIGNED.value
                    and not row["claim_correct"]
                    for row in records
                ),
                "counterfactual_false_accepts": sum(
                    row["counterfactual_features"]["original_pixel_status"]
                    == AlignmentStatus.ALIGNED.value
                    for row in records
                ),
            },
        },
        "decision": {
            "candidate_ready_to_freeze": False,
            "reason": "SROIE is development-only; inspect errors and simplify the selected rule before freezing",
            "untouched_external_dataset_required": True,
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
    result["stable_payload_sha256"] = sha256_bytes(
        canonical_json(result).encode("utf-8")
    )
    report_path = output_dir / "sroie_candidate_lab.json"
    records_path = output_dir / "sroie_candidate_records.jsonl"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with records_path.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{_sha256(path)}  {path.name}"
            for path in (report_path, records_path)
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = aggregate(args.roots, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
