"""Evaluate a sealed Honduran numeric holdout with selective pixel verification.

The primary verifier receives the crop that would exist in production: the
spatially matched Tesseract token box. The exact vector-text box is used only
to locate and score the OCR claim and, when no eligible claim exists, to retain
a clearly labelled diagnostic crop. This prevents ground-truth geometry from
leaking into the measured runtime decision.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import fitz
import numpy as np
import pytesseract
import requests
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pytesseract import Output
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .core import (
    SCHEMA_REPORT,
    absolute_risk_gate,
    canonical_digits,
    canonical_json,
    match_ocr_claim,
    one_digit_counterfactual,
    risk_gate,
    sha256_bytes,
    verify_manifest_hash,
)
from .pixel_digit_alignment import AlignmentStatus, PixelDigitAligner

SUPPORTED_TIERS = ("native_300", "scan_stress_v1")


def session():
    client = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    client.mount("https://", adapter)
    client.mount("http://", adapter)
    client.headers.update({"User-Agent": "OCR-HN-Numeric-Holdout/2.3 evaluation zero-cost"})
    return client


def fetch_bound_pdf(client, document, timeout, pdf_cache):
    expected = str(document["source_sha256"])
    filename = str(document.get("cache_filename") or f"{expected}.pdf")
    if pdf_cache is not None and (pdf_cache / filename).exists():
        data = (pdf_cache / filename).read_bytes()
    else:
        response = client.get(str(document["url"]), timeout=timeout)
        response.raise_for_status()
        data = response.content
    observed = sha256_bytes(data)
    if observed != expected:
        raise RuntimeError(f"source hash mismatch: {observed} != {expected}")
    return data


def pil_page(page, dpi):
    scale = dpi / 72.0
    pix = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB
    )
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def apply_page_tier(image, tier):
    if tier == "native_300":
        return image.convert("RGB")
    if tier != "scan_stress_v1":
        raise ValueError(f"unsupported image tier: {tier}")
    size = image.size
    degraded = ImageOps.grayscale(image).resize(
        (max(1, round(size[0] * 0.55)), max(1, round(size[1] * 0.55))),
        Image.Resampling.LANCZOS,
    )
    degraded = degraded.filter(ImageFilter.GaussianBlur(0.45))
    degraded = ImageEnhance.Contrast(degraded).enhance(0.88)
    degraded = ImageEnhance.Brightness(degraded).enhance(0.98)
    buffer = io.BytesIO()
    degraded.save(
        buffer,
        format="JPEG",
        quality=45,
        optimize=False,
        progressive=False,
    )
    buffer.seek(0)
    with Image.open(buffer) as opened:
        decoded = opened.convert("L")
    return decoded.resize(size, Image.Resampling.BICUBIC).convert("RGB")


def tesseract_tokens(image, language, psm):
    os.environ["OMP_THREAD_LIMIT"] = "1"
    started = time.perf_counter()
    data = pytesseract.image_to_data(
        image,
        lang=language,
        config=f"--oem 1 --psm {psm}",
        output_type=Output.DICT,
    )
    elapsed = time.perf_counter() - started
    tokens = []
    for index, text in enumerate(data.get("text") or []):
        digits = canonical_digits(str(text))
        if not digits:
            continue
        x, y, width, height = (
            int(data[key][index]) for key in ("left", "top", "width", "height")
        )
        try:
            confidence = float(data["conf"][index])
        except Exception:
            confidence = -1.0
        tokens.append(
            {
                "text": str(text),
                "digits": digits,
                "bbox": [x, y, x + width, y + height],
                "confidence": confidence,
            }
        )
    return tokens, {"wall_seconds": elapsed, "tokens": len(tokens)}


def pdf_bbox_to_pixels(bbox_pdf, dpi):
    scale = dpi / 72.0
    return [float(value) * scale for value in bbox_pdf]


def crop_from_pixel_bbox(image, bbox_pixels, margin=2):
    x0, y0, x1, y1 = map(float, bbox_pixels)
    box = [
        max(0, int(np.floor(x0)) - margin),
        max(0, int(np.floor(y0)) - margin),
        min(image.width, int(np.ceil(x1)) + margin),
        min(image.height, int(np.ceil(y1)) + margin),
    ]
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("empty crop")
    return image.crop(tuple(box)), box


def crop_from_bbox(image, bbox_pdf, dpi, margin=2):
    return crop_from_pixel_bbox(
        image, pdf_bbox_to_pixels(bbox_pdf, dpi), margin=margin
    )


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def eligibility(truth, matched):
    if matched is None:
        return "", False, "NO_SPATIAL_MATCH"
    claim = canonical_digits(str(matched.get("text") or ""))
    if not claim:
        return "", False, "EMPTY_CLAIM"
    if len(claim) != len(truth):
        return claim, False, "LENGTH_MISMATCH_OUTSIDE_SUBSTITUTION_SCOPE"
    if float((matched.get("match") or {}).get("truth_coverage") or 0) < 0.50:
        return claim, False, "LOW_SPATIAL_COVERAGE"
    return claim, True, "ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM"


def gate_rows(rows, factor, alpha, minimum_accepted, minimum_coverage):
    eligible = [row for row in rows if row["tesseract"]["eligible"]]
    accepted = [row for row in eligible if row["verifier"]["accept"]]
    return risk_gate(
        baseline_false=sum(
            not row["tesseract"]["claim_correct"] for row in eligible
        ),
        baseline_total=len(eligible),
        candidate_false=sum(
            row["verifier"]["false_accept"] for row in accepted
        ),
        candidate_total=len(accepted),
        eligible_total=max(len(eligible), 1),
        factor=factor,
        alpha=alpha,
        minimum_accepted=minimum_accepted,
        minimum_coverage=minimum_coverage,
    )


def evaluate_manifest(
    manifest: Mapping[str, Any],
    *,
    dpi,
    language,
    psm,
    tier,
    pdf_timeout,
    pdf_cache,
    evidence_dir,
    minimum_accepted,
    minimum_coverage,
    factor,
    alpha,
    minimum_institution_fold_pass_fraction,
    counterfactual_maximum_risk,
    counterfactual_minimum_total,
):
    if not verify_manifest_hash(manifest):
        raise RuntimeError("manifest hash verification failed")
    if not manifest.get("summary", {}).get("complete"):
        raise RuntimeError("manifest is incomplete")
    if tier not in SUPPORTED_TIERS:
        raise ValueError(tier)
    client = session()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    aligner = PixelDigitAligner()
    _ = aligner._bank
    aligner_init = time.perf_counter() - started
    crops_by_doc = defaultdict(list)
    for crop in manifest["crops"]:
        crops_by_doc[int(crop["document_index"])].append(crop)
    observations = []
    page_runtimes = []
    for index, document in enumerate(manifest["documents"]):
        selected = crops_by_doc[index]
        if len(selected) != 1:
            raise RuntimeError("exactly one crop per OCID required")
        spec = selected[0]
        data = fetch_bound_pdf(client, document, pdf_timeout, pdf_cache)
        pdf = fitz.open(stream=data, filetype="pdf")
        try:
            page_index = int(spec["page_index"])
            image = apply_page_tier(pil_page(pdf[page_index], dpi), tier)
            tokens, runtime = tesseract_tokens(image, language, psm)
            page_runtimes.append(
                {
                    "document_index": index,
                    "unit_id": spec["unit_id"],
                    "page_index": page_index,
                    **runtime,
                }
            )
            truth_bbox_pixels = pdf_bbox_to_pixels(spec["bbox_pdf"], dpi)
            matched = match_ocr_claim(truth_bbox_pixels, tokens)
            claim, eligible, reason = eligibility(str(spec["truth"]), matched)
            correct = eligible and claim == spec["truth"]

            if eligible:
                verifier_bbox_pixels = list(matched["bbox"])
                crop_source = "tesseract_matched_bbox"
            else:
                verifier_bbox_pixels = truth_bbox_pixels
                crop_source = "truth_bbox_diagnostic_only"
            crop_image, crop_box = crop_from_pixel_bbox(
                image, verifier_bbox_pixels
            )
            crop_data = png_bytes(crop_image)
            crop_path = evidence_dir / f"{spec['crop_id']}.png"
            crop_path.write_bytes(crop_data)

            verifier_started = time.perf_counter()
            if eligible:
                decision = aligner.align(crop_image, claim)
                status = decision.status.value
                prediction = decision.predicted
                details = decision.to_data(include_positions=False)
            else:
                status = AlignmentStatus.INDETERMINATE.value
                prediction = ""
                details = {"status": status, "reason": reason}
            verifier_seconds = time.perf_counter() - verifier_started

            counter = one_digit_counterfactual(
                str(spec["truth"]), str(spec["crop_id"])
            )
            if eligible:
                counter_started = time.perf_counter()
                counter_decision = aligner.align(crop_image, counter)
                counter_seconds = time.perf_counter() - counter_started
                counter_status = counter_decision.status.value
                counter_prediction = counter_decision.predicted
                counter_false_accept = (
                    counter_decision.status == AlignmentStatus.ALIGNED
                )
            else:
                counter_seconds = 0.0
                counter_status = AlignmentStatus.INDETERMINATE.value
                counter_prediction = ""
                counter_false_accept = False

            observations.append(
                {
                    "crop_id": spec["crop_id"],
                    "unit_id": spec["unit_id"],
                    "document_index": index,
                    "institution": spec["institution"],
                    "ocid": spec["ocid"],
                    "page_index": page_index,
                    "truth": spec["truth"],
                    "bbox_pdf": spec["bbox_pdf"],
                    "truth_bbox_pixels": truth_bbox_pixels,
                    "verifier_bbox_pixels": crop_box,
                    "crop_source": crop_source,
                    "image_tier": tier,
                    "crop_file": f"crops/{crop_path.name}",
                    "crop_png_sha256": sha256_bytes(crop_data),
                    "tesseract": {
                        "claim": claim,
                        "eligible": eligible,
                        "eligibility_reason": reason,
                        "claim_correct": correct,
                        "matched": matched,
                    },
                    "verifier": {
                        "status": status,
                        "prediction": prediction,
                        "accept": eligible and status == "ALIGNED",
                        "correct_accept": (
                            eligible and status == "ALIGNED" and correct
                        ),
                        "false_accept": (
                            eligible and status == "ALIGNED" and not correct
                        ),
                        "runtime_seconds": verifier_seconds,
                        "details": details,
                    },
                    "counterfactual": {
                        "eligible": eligible,
                        "claim": counter,
                        "status": counter_status,
                        "prediction": counter_prediction,
                        "false_accept": counter_false_accept,
                        "runtime_seconds": counter_seconds,
                    },
                }
            )
        finally:
            pdf.close()
        print(
            json.dumps(
                {
                    "document": index + 1,
                    "total_documents": len(manifest["documents"]),
                    "observations": len(observations),
                    "tier": tier,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    eligible = [row for row in observations if row["tesseract"]["eligible"]]
    accepted = [row for row in eligible if row["verifier"]["accept"]]
    main_gate = gate_rows(
        observations, factor, alpha, minimum_accepted, minimum_coverage
    )
    institutions = sorted({str(row["institution"]) for row in observations})
    folds = []
    for institution in institutions:
        subset = [
            row for row in observations if row["institution"] != institution
        ]
        fold_eligible = sum(
            row["tesseract"]["eligible"] for row in subset
        )
        scaled = max(
            1,
            math.floor(
                minimum_accepted
                * (fold_eligible / max(len(eligible), 1))
                * 0.75
            ),
        )
        folds.append(
            {
                "held_out_institution": institution,
                "remaining_crops": len(subset),
                "gate": gate_rows(
                    subset, factor, alpha, scaled, minimum_coverage
                ),
            }
        )
    fold_passes = sum(bool(row["gate"]["pass"]) for row in folds)
    fold_fraction = fold_passes / len(folds) if folds else 0
    stability = {
        "folds": folds,
        "fold_count": len(folds),
        "passes": fold_passes,
        "pass_fraction": fold_fraction,
        "minimum_required_pass_fraction": minimum_institution_fold_pass_fraction,
        "pass": bool(
            folds
            and fold_fraction >= minimum_institution_fold_pass_fraction
        ),
    }

    counterfactual_rows = [
        row for row in observations if row["counterfactual"]["eligible"]
    ]
    counterfactual_false = sum(
        row["counterfactual"]["false_accept"]
        for row in counterfactual_rows
    )
    counterfactual_gate = absolute_risk_gate(
        false_accepts=counterfactual_false,
        total=len(counterfactual_rows),
        maximum_upper_risk=counterfactual_maximum_risk,
        minimum_total=counterfactual_minimum_total,
        alpha=alpha,
    )
    if not main_gate["pass"]:
        verdict = main_gate["reason"]
    elif not stability["pass"]:
        verdict = "INSTITUTION_STABILITY_GATE_FAILED"
    elif not counterfactual_gate["pass"]:
        verdict = "COUNTERFACTUAL_RISK_GATE_FAILED"
    else:
        verdict = "PASS_HN_NUMERIC_SUBSTITUTION_RISK_10X"

    institution_summary = {}
    for institution in institutions:
        rows = [
            row for row in observations if row["institution"] == institution
        ]
        institution_summary[institution] = {
            "crops": len(rows),
            "eligible_baseline_claims": sum(
                row["tesseract"]["eligible"] for row in rows
            ),
            "baseline_false": sum(
                row["tesseract"]["eligible"]
                and not row["tesseract"]["claim_correct"]
                for row in rows
            ),
            "candidate_accepts": sum(
                row["verifier"]["accept"] for row in rows
            ),
            "candidate_false": sum(
                row["verifier"]["false_accept"] for row in rows
            ),
        }

    verifier_times = [
        row["verifier"]["runtime_seconds"] for row in eligible
    ]
    counterfactual_times = [
        row["counterfactual"]["runtime_seconds"]
        for row in counterfactual_rows
    ]
    page_times = [row["wall_seconds"] for row in page_runtimes]
    mean_page = sum(page_times) / len(page_times) if page_times else None
    mean_verifier = (
        sum(verifier_times) / len(verifier_times)
        if verifier_times
        else None
    )

    payload = {
        "schema": SCHEMA_REPORT,
        "source": {
            "manifest_sha256": manifest["manifest_sha256"],
            "manifest_summary": manifest["summary"],
        },
        "runtime": {
            "dpi": dpi,
            "image_tier": tier,
            "image_tier_recipe": (
                "native 300-DPI render"
                if tier == "native_300"
                else "55% downsample, blur 0.45, contrast 0.88, brightness 0.98, JPEG Q45, upscale"
            ),
            "tesseract_language": language,
            "tesseract_psm": psm,
            "aligner_initialization_seconds": aligner_init,
            "pages": len(page_runtimes),
            "mean_tesseract_page_seconds": mean_page,
            "mean_verifier_token_ms": (
                1000 * mean_verifier
                if mean_verifier is not None
                else None
            ),
            "median_verifier_token_ms": (
                1000 * float(np.median(verifier_times))
                if verifier_times
                else None
            ),
            "p95_verifier_token_ms": (
                1000 * float(np.quantile(verifier_times, 0.95))
                if verifier_times
                else None
            ),
            "mean_counterfactual_token_ms": (
                1000
                * sum(counterfactual_times)
                / len(counterfactual_times)
                if counterfactual_times
                else None
            ),
            "mean_verifier_overhead_fraction_of_page_ocr": (
                mean_verifier / mean_page
                if mean_page and mean_verifier is not None
                else None
            ),
        },
        "summary": {
            "crops": len(observations),
            "unique_ocids": len(
                {row["unit_id"] for row in observations}
            ),
            "production_bbox_crops": len(eligible),
            "diagnostic_truth_bbox_crops": len(observations) - len(eligible),
            "eligible_equal_length_spatial_claims": len(eligible),
            "ineligible_claims": len(observations) - len(eligible),
            "baseline_correct": sum(
                row["tesseract"]["claim_correct"] for row in eligible
            ),
            "baseline_false": sum(
                not row["tesseract"]["claim_correct"] for row in eligible
            ),
            "candidate_accepts": len(accepted),
            "candidate_correct": sum(
                row["verifier"]["correct_accept"] for row in accepted
            ),
            "candidate_false": sum(
                row["verifier"]["false_accept"] for row in accepted
            ),
            "counterfactual_false_accepts": counterfactual_false,
            "counterfactual_total": len(counterfactual_rows),
            "institutions": len(institutions),
        },
        "risk_gate": main_gate,
        "institution_stability": stability,
        "counterfactual_gate": counterfactual_gate,
        "institution_summary": institution_summary,
        "page_runtimes": page_runtimes,
        "observations": observations,
        "decision": {
            "verdict": verdict,
            "pass": verdict
            == "PASS_HN_NUMERIC_SUBSTITUTION_RISK_10X",
            "automatic_production_change": False,
            "next": (
                "freeze and open an untouched native holdout"
                if verdict == "PASS_HN_NUMERIC_SUBSTITUTION_RISK_10X"
                else "retain abstention and dimension the next untouched unique-OCID sample without tuning"
            ),
        },
        "research_design": {
            "unit_of_inference": "one crop from one unique OCDS OCID",
            "selective_prediction": "accept or abstain; false acceptance is primary",
            "substitution_scope": "same-length spatial claims only",
            "primary_verifier_crop": "spatially matched Tesseract token bbox",
            "ground_truth_bbox_use": "claim matching and diagnostic crop only",
            "threshold_tuning_on_holdout": False,
            "same_holdout_baseline": True,
            "one_sided_exact_binomial_bounds": True,
            "leave_one_institution_out_stability": True,
            "counterfactual_single_digit_negatives": True,
        },
        "constraints": manifest["constraints"],
    }
    payload["stable_payload_sha256"] = sha256_bytes(
        canonical_json(payload).encode("utf-8")
    )
    return payload


def parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_hn_numeric_holdout_v1/run/evaluation"),
    )
    parser.add_argument("--pdf-cache", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--language", default="spa")
    parser.add_argument("--psm", type=int, default=3)
    parser.add_argument(
        "--tier", choices=SUPPORTED_TIERS, default="scan_stress_v1"
    )
    parser.add_argument("--pdf-timeout", type=float, default=90)
    parser.add_argument("--minimum-accepted", type=int, default=40)
    parser.add_argument("--minimum-coverage", type=float, default=0.30)
    parser.add_argument("--target-reduction-factor", type=float, default=10)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument(
        "--minimum-institution-fold-pass-fraction",
        type=float,
        default=0.80,
    )
    parser.add_argument(
        "--counterfactual-maximum-risk", type=float, default=0.03
    )
    parser.add_argument(
        "--counterfactual-minimum-total", type=int, default=100
    )
    return parser


def main():
    args = parser().parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = evaluate_manifest(
        manifest,
        dpi=args.dpi,
        language=args.language,
        psm=args.psm,
        tier=args.tier,
        pdf_timeout=args.pdf_timeout,
        pdf_cache=args.pdf_cache,
        evidence_dir=args.output_dir / "crops",
        minimum_accepted=args.minimum_accepted,
        minimum_coverage=args.minimum_coverage,
        factor=args.target_reduction_factor,
        alpha=args.alpha,
        minimum_institution_fold_pass_fraction=(
            args.minimum_institution_fold_pass_fraction
        ),
        counterfactual_maximum_risk=(
            args.counterfactual_maximum_risk
        ),
        counterfactual_minimum_total=(
            args.counterfactual_minimum_total
        ),
    )
    path = args.output_dir / "evaluation.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "evaluation.sha256").write_text(
        f"{sha256_bytes(path.read_bytes())}  evaluation.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(path),
                "summary": report["summary"],
                "risk_gate": report["risk_gate"],
                "institution_stability": {
                    key: report["institution_stability"][key]
                    for key in (
                        "fold_count",
                        "passes",
                        "pass_fraction",
                        "pass",
                    )
                },
                "counterfactual_gate": report["counterfactual_gate"],
                "decision": report["decision"],
                "stable_payload_sha256": report[
                    "stable_payload_sha256"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
