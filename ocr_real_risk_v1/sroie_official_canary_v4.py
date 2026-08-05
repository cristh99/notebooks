"""Zero-cost development canary on original SROIE task-1 files."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image

from .pixel_digit_alignment_v4 import AlignmentStatus, PixelDigitAlignerV4, render_numeric_token
from .sroie_official_protocol_v4 import (
    BoxToken,
    Match,
    Scope,
    canonical_numeric,
    classify_scope,
    match_geometry_only,
    padded_crop,
    parse_tesseract_tsv,
    parse_truth,
    sha256_image,
    wilson_interval,
)

__all__ = ["BoxToken", "Match", "Scope", "canonical_numeric", "classify_scope", "match_geometry_only", "parse_truth", "run"]


@dataclass(frozen=True, slots=True)
class CaseResult:
    page_id: str
    scope: str
    candidate_text: str
    candidate_digits: str
    candidate_confidence: float | None
    truth_text: str
    truth_digits: str
    baseline_correct: bool
    alignment_status: str
    predicted_digits: str | None
    runtime_ms: float | None
    geometry_score: float
    iou: float
    smaller_coverage: float
    vertical_overlap: float
    crop_sha256: str | None
    decision_sha256: str | None


def run_tesseract_tsv(image_path: Path) -> tuple[str, float]:
    command = ["tesseract", str(image_path), "stdout", "-l", "eng", "--oem", "1", "--psm", "3", "tsv"]
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "1"
    started = time.perf_counter()
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", env=environment)
    return result.stdout, time.perf_counter() - started


def summarize(cases: list[CaseResult], truth_units: int, candidates: int, tesseract_seconds: float, warmup_seconds: float) -> dict[str, object]:
    scoped = [row for row in cases if row.scope == Scope.SAME_LENGTH_SUBSTITUTION.value]
    aligned = [row for row in scoped if row.alignment_status == AlignmentStatus.ALIGNED.value]
    misaligned = [row for row in scoped if row.alignment_status == AlignmentStatus.MISALIGNED.value]
    indeterminate = [row for row in scoped if row.alignment_status == AlignmentStatus.INDETERMINATE.value]
    baseline_wrong = sum(not row.baseline_correct for row in scoped)
    wrong_aligned = sum(not row.baseline_correct for row in aligned)
    baseline_error = baseline_wrong / len(scoped) if scoped else 0.0
    accepted_error = wrong_aligned / len(aligned) if aligned else 0.0
    baseline_low, baseline_upper = wilson_interval(baseline_wrong, len(scoped))
    accepted_low, accepted_upper = wilson_interval(wrong_aligned, len(aligned))
    observed = baseline_error / accepted_error if accepted_error else (math.inf if baseline_error else 1.0)
    conservative = baseline_low / accepted_upper if accepted_upper else math.inf
    runtimes = [row.runtime_ms for row in scoped if row.runtime_ms is not None]
    coverage = len(aligned) / len(scoped) if scoped else 0.0
    return {
        "all_numeric": {"truth_units": truth_units, "candidate_count": candidates, "geometrically_matched": len(cases), "unmatched_truth": truth_units - len(cases), "unmatched_candidates": candidates - len(cases)},
        "scope_partition": {"same_length_substitution": len(scoped), "out_of_scope_length_or_partial_match": len(cases) - len(scoped)},
        "same_length_baseline": {"correct": len(scoped) - baseline_wrong, "wrong": baseline_wrong, "error_rate": baseline_error, "wilson_95": [baseline_low, baseline_upper]},
        "pixel_verifier": {
            "aligned_accept": len(aligned), "misaligned_quarantine": len(misaligned), "indeterminate_abstain": len(indeterminate),
            "accepted_coverage": coverage, "wrong_accepted": wrong_aligned,
            "correct_quarantined": sum(row.baseline_correct for row in misaligned),
            "wrong_detected": sum(not row.baseline_correct for row in misaligned),
            "wrong_abstained": sum(not row.baseline_correct for row in indeterminate),
            "wrong_not_accepted_rate": (sum(not row.baseline_correct for row in misaligned + indeterminate) / baseline_wrong if baseline_wrong else 0.0),
            "accepted_error_rate": accepted_error, "accepted_error_wilson_95": [accepted_low, accepted_upper],
            "observed_error_reduction_factor": observed, "conservative_error_reduction_factor": conservative,
            "quality_10x_gate": bool(conservative >= 10.0 and coverage >= 0.25),
        },
        "runtime": {
            "tesseract_full_page_seconds": tesseract_seconds, "pixel_bank_warmup_seconds": warmup_seconds,
            "pixel_selective_warm_seconds": sum(runtimes) / 1000.0,
            "pixel_warm_median_ms": statistics.median(runtimes) if runtimes else 0.0,
            "pixel_warm_p95_ms": sorted(runtimes)[max(0, math.ceil(0.95 * len(runtimes)) - 1)] if runtimes else 0.0,
            "speed_10x_gate": "NOT_MEASURED_END_TO_END",
        },
    }


def run(dataset_root: Path, output_path: Path, page_ids: Sequence[str]) -> dict[str, object]:
    if len(page_ids) != len(set(page_ids)):
        raise ValueError("page IDs must be unique")
    aligner = PixelDigitAlignerV4()
    started = time.perf_counter()
    aligner.align(render_numeric_token("1234", aligner.template_fonts[0]), "1234")
    warmup = time.perf_counter() - started
    all_truth: list[BoxToken] = []
    all_candidates: list[BoxToken] = []
    matches: list[Match] = []
    images: dict[str, Image.Image] = {}
    pages: list[dict[str, object]] = []
    tesseract_seconds = 0.0
    for page_id in page_ids:
        image_path = dataset_root / "img" / f"{page_id}.jpg"
        truth_path = dataset_root / "box" / f"{page_id}.txt"
        if not image_path.is_file() or not truth_path.is_file():
            raise FileNotFoundError(page_id)
        truth = parse_truth(truth_path, page_id)
        tsv, elapsed = run_tesseract_tsv(image_path)
        candidates = parse_tesseract_tsv(tsv, page_id)
        paired = match_geometry_only(candidates, truth)
        images[page_id] = Image.open(image_path).convert("RGB")
        all_truth.extend(truth); all_candidates.extend(candidates); matches.extend(paired); tesseract_seconds += elapsed
        pages.append({"page_id": page_id, "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(), "truth_sha256": hashlib.sha256(truth_path.read_bytes()).hexdigest(), "truth_units": len(truth), "candidate_count": len(candidates), "matched": len(paired), "tesseract_seconds": elapsed})

    cases: list[CaseResult] = []
    for match in matches:
        scope = classify_scope(match)
        if scope == Scope.SAME_LENGTH_SUBSTITUTION:
            crop = padded_crop(images[match.candidate.page_id], match.candidate.bbox)
            started = time.perf_counter(); decision = aligner.align(crop, match.candidate.digits); runtime = (time.perf_counter() - started) * 1000.0
            status, predicted, crop_hash, decision_hash = decision.status.value, decision.predicted, sha256_image(crop), decision.decision_sha256
        else:
            status, predicted, runtime, crop_hash, decision_hash = "NOT_EVALUATED_OUT_OF_SCOPE", None, None, None, None
        cases.append(CaseResult(match.candidate.page_id, scope.value, match.candidate.text, match.candidate.digits, match.candidate.confidence, match.truth.text, match.truth.digits, match.candidate.digits == match.truth.digits, status, predicted, runtime, match.geometry_score, match.iou, match.smaller_coverage, match.vertical_overlap, crop_hash, decision_hash))

    summary = summarize(cases, len(all_truth), len(all_candidates), tesseract_seconds, warmup)
    report: dict[str, object] = {
        "schema": "ocr-sroie-official-task1-development-canary-v4/1", "status": "DEVELOPMENT_CANARY_ONLY",
        "promotion_status": "BLOCKED", "external_certification": False, "spend_usd": 0.0,
        "source": {"dataset": "SROIE 2019 task 1 original public Google Drive files", "page_ids": list(page_ids), "pages": len(page_ids), "selection": "fixed convenience subset before execution"},
        "protocol": {"candidate_selection": "Tesseract TSV ASCII numeric tokens, 4-12 digits", "geometric_matching": "one-to-one geometry without token strings", "visual_scope": Scope.SAME_LENGTH_SUBSTITUTION.value, "truth_use": "post-selection evaluation only"},
        "environment": {"tesseract_version": subprocess.run(["tesseract", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0], "language": "eng", "oem": 1, "psm": 3, "omp_thread_limit": 1, "pixel_configuration_sha256": aligner.configuration_sha256},
        "summary": summary, "pages": pages, "cases": [asdict(row) for row in cases],
        "decision": {"production": "BLOCKED", "external_10x_quality": "PASS_DEVELOPMENT_ONLY" if summary["pixel_verifier"]["quality_10x_gate"] else "BLOCKED", "external_10x_speed": "NOT_MEASURED_END_TO_END", "semantic_context": "SEPARATE_GATE_REQUIRED"},
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    report["report_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--dataset-root", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--page-ids", nargs="+", required=True)
    args = parser.parse_args(); report = run(args.dataset_root, args.output, args.page_ids)
    print(json.dumps(report["summary"], indent=2, sort_keys=True)); print("report_sha256", report["report_sha256"])


if __name__ == "__main__":
    main()
