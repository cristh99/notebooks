"""Replay sealed dual-source truth locations through full-page Tesseract.

Truth locations and documents are inherited unchanged from the completed
process-disjoint development validation. Tesseract sees the full rendered page;
the verifier receives only the spatially matched Tesseract token box. The native
truth box is used for matching and for a clearly labelled diagnostic crop when
no eligible claim exists, never as the primary verifier input.
"""
from __future__ import annotations

import argparse
import hashlib
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

import pytesseract
from PIL import Image
from pytesseract import Output

from .aggregate_disjoint_validation import (
    _stable_payload_hash,
    _verify_hash_manifest,
    deduplicate_physical_evidence,
    physical_location_identity,
)
from .core import Candidate, canonical_json, p95, sha256_bytes, sha256_file
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .final_partition import process_key
from .isolated_crop import isolated_native_word_box
from .pdf_pipeline import download_pdf, run
from .pixel_digit_alignment import PixelDigitAligner

MANIFEST_SCHEMA = "ocr-real-risk-full-page-spatial-manifest/1"
REPORT_SCHEMA = "ocr-real-risk-full-page-spatial-replay/1"
DPI = 300
LANGUAGE = "spa"
PSM = 3
FAMILY_ALPHA = 0.05
ALPHA_PER_LEG = FAMILY_ALPHA / 4.0
MINIMUM_TRUTH_COVERAGE = 0.50
MATCH_MINIMUM_TRUTH_COVERAGE = 0.35
TARGET_REDUCTION = 10.0
MINIMUM_ACCEPTED = 100
MINIMUM_COVERAGE = 0.25
COUNTERFACTUAL_MAXIMUM_RISK = 0.01
COUNTERFACTUAL_MINIMUM_TOTAL = 100
_DIGITS_RE = re.compile(r"\D+")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digits(value: object) -> str:
    return _DIGITS_RE.sub("", str(value or ""))


def _evidence_key(
    identity: tuple[str, int, tuple[float, ...]],
) -> str:
    source_sha256, page_number, bbox_pt = identity
    return sha256_bytes(
        canonical_json(
            {
                "source_sha256": source_sha256,
                "page_number": page_number,
                "bbox_pt": list(bbox_pt),
            }
        ).encode("utf-8")
    )


def _stable_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = sha256_bytes(
        canonical_json(result).encode("utf-8")
    )
    return result


def verify_manifest(manifest: Mapping[str, Any]) -> bool:
    expected = str(manifest.get("manifest_sha256") or "")
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    return expected == sha256_bytes(canonical_json(payload).encode("utf-8"))


def build_manifest(roots: Iterable[Path]) -> dict[str, Any]:
    annotated_observations: list[dict[str, Any]] = []
    identity_groups: dict[
        tuple[str, int, tuple[float, ...]],
        list[dict[str, Any]],
    ] = defaultdict(list)
    source_reports: list[dict[str, Any]] = []
    shard_indices: set[int] = set()

    for root in sorted(roots):
        _verify_hash_manifest(root)
        report_path = root / "reports/real_numeric_risk_holdout.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        _stable_payload_hash(report)
        protocol = report["protocol"]["disjoint_validation"]
        shard_index = int(protocol["shard_index"])
        if shard_index in shard_indices:
            raise RuntimeError(f"duplicate source shard: {shard_index}")
        shard_indices.add(shard_index)
        source_reports.append(
            {
                "shard_index": shard_index,
                "report_sha256": _sha256(report_path),
                "stable_payload_sha256": report["stable_payload_sha256"],
                "documents_attempted": report["execution"]["documents_attempted"],
                "process_associated_locations": report["execution"][
                    "documents_with_tokens"
                ],
            }
        )
        documents: dict[str, dict[str, Any]] = {
            str(document["document_id"]): document
            for document in report["documents"]
        }
        if len(documents) != len(report["documents"]):
            raise RuntimeError("duplicate document_id inside a source shard")
        for observation in report["observations"]:
            document = documents.get(str(observation["document_id"]))
            if document is None:
                raise RuntimeError("source observation lacks a bound document")
            candidate = Candidate(**document["candidate"])
            selected = document.get("native_index", {}).get("selected")
            pages = document.get("pages") or []
            if not selected or len(pages) != 1 or "image_size" not in pages[0]:
                raise RuntimeError("source observation lacks sealed native geometry")
            annotated = dict(observation)
            annotated["_process_key"] = process_key(candidate)
            annotated["_shard_index"] = shard_index
            annotated["_candidate"] = dict(document["candidate"])
            annotated["_selected"] = selected
            annotated["_prior_page_image_size"] = pages[0]["image_size"]
            annotated_observations.append(annotated)
            identity_groups[physical_location_identity(annotated)].append(annotated)

    if shard_indices != set(range(16)):
        raise RuntimeError("source validation must contain exactly shards 0..15")
    unique, reuse = deduplicate_physical_evidence(annotated_observations)
    if len(unique) != 174:
        raise RuntimeError(f"expected 174 unique evidence locations, found {len(unique)}")

    records: list[dict[str, Any]] = []
    for representative in unique:
        identity = physical_location_identity(representative)
        rows = sorted(
            identity_groups[identity],
            key=lambda row: (
                str(row["_process_key"]),
                int(row["_shard_index"]),
            ),
        )
        selected = representative["_selected"]
        candidate = representative["_candidate"]
        record = {
            "evidence_key": _evidence_key(identity),
            "source_sha256": representative["source_sha256"],
            "source_urls": [
                row["_candidate"]["url"] for row in rows
            ],
            "source_url_sha256": [
                sha256_bytes(row["_candidate"]["url"].encode("utf-8"))
                for row in rows
            ],
            "associated_process_keys": [
                row["_process_key"] for row in rows
            ],
            "associated_process_count": len(rows),
            "representative_process_key": representative["_process_key"],
            "representative_process": candidate["process"],
            "representative_ocid": candidate["ocid"],
            "institution_code": candidate["institution_code"],
            "institution_name": candidate["institution_name"],
            "document_type": candidate["document_type"],
            "page_number": int(representative["page_number"]),
            "page_width_pt": float(selected["page_width_pt"]),
            "page_height_pt": float(selected["page_height_pt"]),
            "bbox_pt": [float(value) for value in representative["bbox_pt"]],
            "truth": str(representative["truth"]),
            "counterfactual_claim": str(
                representative["counterfactual_claim"]
            ),
            "prior_isolated_claim": str(
                representative["tesseract_claim"]
            ),
            "prior_isolated_claim_correct": bool(
                representative["claim_correct"]
            ),
            "prior_isolated_verifier_status": str(
                representative["verifier_status"]
            ),
            "prior_isolated_accepted": bool(representative["accepted"]),
            "prior_isolated_false_accepted": bool(
                representative["false_accepted"]
            ),
            "prior_isolated_crop_sha256": str(
                representative["crop_sha256"]
            ),
            "selection_before_full_page_ocr": True,
        }
        records.append(record)
    records.sort(key=lambda row: row["evidence_key"])
    if len({row["evidence_key"] for row in records}) != len(records):
        raise RuntimeError("evidence key collision in full-page replay manifest")

    return _stable_manifest(
        {
            "schema": MANIFEST_SCHEMA,
            "source_validation_run_id": 30953079172,
            "source_aggregate_run_id": 30954894843,
            "source_risk_unit": "unique physical evidence location",
            "source_reports": sorted(
                source_reports, key=lambda row: row["shard_index"]
            ),
            "physical_evidence_reuse": {
                key: value for key, value in reuse.items() if key != "groups"
            },
            "protocol": {
                "selection": (
                    "same 174 unique physical truth locations sealed before "
                    "this replay; no outcome-dependent filtering"
                ),
                "page_input": "full natural page rendered at 300 DPI",
                "tesseract": {
                    "language": LANGUAGE,
                    "oem": 1,
                    "psm": PSM,
                    "output": "image_to_data token boxes",
                },
                "claim_match": (
                    "highest spatial score with at least 35% truth coverage "
                    "or containing the truth center"
                ),
                "eligibility": (
                    "equal canonical digit length and at least 50% truth coverage"
                ),
                "primary_verifier_crop": "matched Tesseract token bbox + 2 px",
                "truth_bbox_primary_decision_use": False,
                "truth_bbox_diagnostic_use": True,
                "family_alpha": FAMILY_ALPHA,
                "alpha_per_leg_bonferroni": ALPHA_PER_LEG,
            },
            "records": records,
        }
    )


def _tesseract_tokens(image: Image.Image) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    os.environ["OMP_THREAD_LIMIT"] = "1"
    started = time.perf_counter()
    data = pytesseract.image_to_data(
        image,
        lang=LANGUAGE,
        config=f"--oem 1 --psm {PSM}",
        output_type=Output.DICT,
    )
    elapsed = time.perf_counter() - started
    valid: list[dict[str, Any]] = []
    invalid_boxes = 0
    for index, text in enumerate(data.get("text") or []):
        digits = _canonical_digits(text)
        if not digits:
            continue
        try:
            x = float(data["left"][index])
            y = float(data["top"][index])
            width = float(data["width"][index])
            height = float(data["height"][index])
            confidence = float(data["conf"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            invalid_boxes += 1
            continue
        values = (x, y, x + width, y + height)
        if not all(math.isfinite(value) for value in values):
            invalid_boxes += 1
            continue
        clipped = [
            max(0.0, values[0]),
            max(0.0, values[1]),
            min(float(image.width), values[2]),
            min(float(image.height), values[3]),
        ]
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            invalid_boxes += 1
            continue
        valid.append(
            {
                "text": str(text),
                "digits": digits,
                "bbox": [
                    int(math.floor(clipped[0])),
                    int(math.floor(clipped[1])),
                    int(math.ceil(clipped[2])),
                    int(math.ceil(clipped[3])),
                ],
                "confidence": confidence,
            }
        )
    return valid, {
        "wall_seconds": elapsed,
        "numeric_tokens": len(valid),
        "invalid_numeric_boxes_filtered": invalid_boxes,
    }


def _iou_and_cover(
    first: Sequence[float], second: Sequence[float]
) -> tuple[float, float, float]:
    ax0, ay0, ax1, ay1 = map(float, first)
    bx0, by0, bx1, by1 = map(float, second)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1e-9, (bx1 - bx0) * (by1 - by0))
    union = area_a + area_b - intersection
    return intersection / union, intersection / area_a, intersection / area_b


def match_ocr_claim(
    truth_bbox: Sequence[float],
    tokens: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    tx0, ty0, tx1, ty1 = map(float, truth_bbox)
    truth_center = ((tx0 + tx1) / 2.0, (ty0 + ty1) / 2.0)
    ranked: list[tuple[float, float, Mapping[str, Any], dict[str, float]]] = []
    for token in tokens:
        bbox = token.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        digits = _canonical_digits(token.get("text"))
        if not digits:
            continue
        iou, truth_cover, token_cover = _iou_and_cover(truth_bbox, bbox)
        bx0, by0, bx1, by1 = map(float, bbox)
        center = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
        distance = math.hypot(
            center[0] - truth_center[0], center[1] - truth_center[1]
        )
        if truth_cover < MATCH_MINIMUM_TRUTH_COVERAGE and not (
            bx0 <= truth_center[0] <= bx1
            and by0 <= truth_center[1] <= by1
        ):
            continue
        score = 3.0 * truth_cover + token_cover + 0.5 * iou - 0.001 * distance
        ranked.append(
            (
                score,
                float(token.get("confidence") or -1.0),
                token,
                {
                    "iou": iou,
                    "truth_coverage": truth_cover,
                    "token_coverage": token_cover,
                    "center_distance": distance,
                    "score": score,
                },
            )
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, token, metrics = ranked[0]
    result = dict(token)
    result["match"] = metrics
    return result


def eligibility(truth: str, matched: Mapping[str, Any] | None) -> tuple[str, bool, str]:
    if matched is None:
        return "", False, "NO_SPATIAL_MATCH"
    claim = _canonical_digits(matched.get("text"))
    if not claim:
        return "", False, "EMPTY_CLAIM"
    if len(claim) != len(truth):
        return claim, False, "LENGTH_MISMATCH_OUTSIDE_SUBSTITUTION_SCOPE"
    coverage = float((matched.get("match") or {}).get("truth_coverage") or 0.0)
    if coverage < MINIMUM_TRUTH_COVERAGE:
        return claim, False, "LOW_SPATIAL_COVERAGE"
    return claim, True, "ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM"


def _truth_bbox_pixels(record: Mapping[str, Any], image: Image.Image) -> list[float]:
    scale_x = image.width / float(record["page_width_pt"])
    scale_y = image.height / float(record["page_height_pt"])
    x0, y0, x1, y1 = (float(value) for value in record["bbox_pt"])
    return [x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y]


def _crop_box(
    image: Image.Image,
    bbox: Sequence[float],
    *,
    margin: int,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = map(float, bbox)
    box = (
        max(0, math.floor(x0) - margin),
        max(0, math.floor(y0) - margin),
        min(image.width, math.ceil(x1) + margin),
        min(image.height, math.ceil(y1) + margin),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("empty verifier crop")
    return box


def _status(decision: Any) -> str:
    status = getattr(decision, "status", "")
    return str(getattr(status, "value", status))


def _prediction(decision: Any) -> str:
    return str(getattr(decision, "predicted", ""))


def _download_bound_pdf(record: Mapping[str, Any], destination: Path) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for url in record["source_urls"]:
        for attempt in range(1, 4):
            destination.unlink(missing_ok=True)
            acquisition = download_pdf(str(url), destination)
            acquisition["attempt"] = attempt
            acquisition["url_sha256"] = sha256_bytes(str(url).encode("utf-8"))
            if acquisition.get("status") == "ACQUIRED":
                if acquisition.get("sha256") != record["source_sha256"]:
                    raise RuntimeError(
                        "source PDF changed after truth selection: "
                        f"{record['evidence_key']}"
                    )
                return acquisition
            failures.append(acquisition)
            time.sleep(0.5 * attempt)
    raise RuntimeError(
        "all bound source URLs failed for evidence "
        f"{record['evidence_key']}: {failures}"
    )


def evaluate_manifest(
    manifest: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    if not verify_manifest(manifest):
        raise RuntimeError("manifest hash verification failed")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise RuntimeError("unexpected manifest schema")
    records = list(manifest.get("records") or [])
    if len(records) != 174:
        raise RuntimeError("full-page replay requires all 174 sealed locations")

    scratch = output_dir / "scratch"
    crops = output_dir / "crops"
    scratch.mkdir(parents=True, exist_ok=True)
    crops.mkdir(parents=True, exist_ok=True)
    aligner = PixelDigitAligner()
    _ = aligner._bank  # type: ignore[attr-defined]
    observations: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()

    for index, record in enumerate(records, start=1):
        work = scratch / str(record["evidence_key"])
        work.mkdir(parents=True, exist_ok=True)
        pdf_path = work / "source.pdf"
        acquisition = _download_bound_pdf(record, pdf_path)
        stem = work / "page"
        render_started = time.perf_counter()
        run(
            [
                "pdftoppm",
                "-f",
                str(record["page_number"]),
                "-l",
                str(record["page_number"]),
                "-singlefile",
                "-r",
                str(DPI),
                "-png",
                str(pdf_path),
                str(stem),
            ],
            timeout=120,
        )
        render_seconds = time.perf_counter() - render_started
        page_path = stem.with_suffix(".png")
        if not page_path.exists():
            raise RuntimeError("pdftoppm did not create the selected page")
        with Image.open(page_path) as opened:
            image = opened.convert("RGB")

        tokens, page_ocr = _tesseract_tokens(image)
        truth_bbox = _truth_bbox_pixels(record, image)
        matched = match_ocr_claim(truth_bbox, tokens)
        claim, eligible, reason = eligibility(str(record["truth"]), matched)
        reason_counts[reason] += 1
        correct = eligible and claim == record["truth"]
        if eligible:
            crop_source = "tesseract_matched_bbox"
            crop_box = _crop_box(image, matched["bbox"], margin=2)
        else:
            crop_source = "truth_bbox_diagnostic_only"
            crop_box = isolated_native_word_box(
                record["bbox_pt"],
                (
                    float(record["page_width_pt"]),
                    float(record["page_height_pt"]),
                ),
                image.size,
            )
        crop = image.crop(crop_box)
        crop_path = crops / f"{record['evidence_key']}.png"
        crop.save(crop_path, optimize=False)

        if eligible:
            started = time.perf_counter()
            decision = aligner.align(crop, claim)
            verifier_seconds = time.perf_counter() - started
            verifier_status = _status(decision)
            verifier_prediction = _prediction(decision)
            counter_started = time.perf_counter()
            counter = aligner.align(crop, str(record["counterfactual_claim"]))
            counter_seconds = time.perf_counter() - counter_started
            counter_status = _status(counter)
            counter_prediction = _prediction(counter)
        else:
            verifier_seconds = 0.0
            verifier_status = "INDETERMINATE"
            verifier_prediction = ""
            counter_seconds = 0.0
            counter_status = "INDETERMINATE"
            counter_prediction = ""
        accepted = eligible and verifier_status == "ALIGNED"
        row = {
            "evidence_key": record["evidence_key"],
            "source_sha256": record["source_sha256"],
            "page_number": record["page_number"],
            "bbox_pt": record["bbox_pt"],
            "truth_bbox_pixels": truth_bbox,
            "truth": record["truth"],
            "institution_code": record["institution_code"],
            "institution_name": record["institution_name"],
            "document_type": record["document_type"],
            "associated_process_count": record["associated_process_count"],
            "acquisition": acquisition,
            "page": {
                "image_size": list(image.size),
                "render_seconds": render_seconds,
                "ocr": page_ocr,
            },
            "tesseract": {
                "claim": claim,
                "eligible": eligible,
                "eligibility_reason": reason,
                "claim_correct": correct,
                "matched": matched,
            },
            "verifier": {
                "crop_source": crop_source,
                "crop_box_pixels": list(crop_box),
                "crop_file": f"crops/{crop_path.name}",
                "crop_sha256": sha256_file(crop_path),
                "status": verifier_status,
                "prediction": verifier_prediction,
                "accepted": accepted,
                "correct_accept": accepted and correct,
                "false_accept": accepted and not correct,
                "runtime_seconds": verifier_seconds,
            },
            "counterfactual": {
                "eligible": eligible,
                "claim": record["counterfactual_claim"],
                "status": counter_status,
                "prediction": counter_prediction,
                "false_accept": eligible and counter_status == "ALIGNED",
                "runtime_seconds": counter_seconds,
            },
            "prior_isolated": {
                "claim": record["prior_isolated_claim"],
                "claim_correct": record["prior_isolated_claim_correct"],
                "verifier_status": record[
                    "prior_isolated_verifier_status"
                ],
                "accepted": record["prior_isolated_accepted"],
                "false_accepted": record[
                    "prior_isolated_false_accepted"
                ],
                "crop_sha256": record["prior_isolated_crop_sha256"],
            },
        }
        observations.append(row)
        shutil.rmtree(work, ignore_errors=True)
        print(
            json.dumps(
                {
                    "evidence": index,
                    "total": len(records),
                    "eligible": sum(
                        item["tesseract"]["eligible"] for item in observations
                    ),
                    "baseline_errors": sum(
                        item["tesseract"]["eligible"]
                        and not item["tesseract"]["claim_correct"]
                        for item in observations
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    eligible_rows = [row for row in observations if row["tesseract"]["eligible"]]
    baseline_false = sum(
        not row["tesseract"]["claim_correct"] for row in eligible_rows
    )
    accepted_rows = [row for row in eligible_rows if row["verifier"]["accepted"]]
    accepted_false = sum(row["verifier"]["false_accept"] for row in accepted_rows)
    counter_false = sum(
        row["counterfactual"]["false_accept"] for row in eligible_rows
    )
    baseline_lower = (
        clopper_pearson_lower(
            baseline_false, len(eligible_rows), ALPHA_PER_LEG
        )
        if eligible_rows
        else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(
            accepted_false, len(accepted_rows), ALPHA_PER_LEG
        )
        if accepted_rows
        else 1.0
    )
    coverage_lower = (
        clopper_pearson_lower(
            len(accepted_rows), len(eligible_rows), ALPHA_PER_LEG
        )
        if eligible_rows
        else 0.0
    )
    counter_upper = (
        clopper_pearson_upper(
            counter_false, len(eligible_rows), ALPHA_PER_LEG
        )
        if eligible_rows
        else 1.0
    )
    reduction_lower = (
        baseline_lower / candidate_upper if candidate_upper > 0 else None
    )
    tenfold_bound = bool(
        baseline_false > 0
        and len(accepted_rows) >= MINIMUM_ACCEPTED
        and coverage_lower >= MINIMUM_COVERAGE
        and candidate_upper <= baseline_lower / TARGET_REDUCTION
        and len(eligible_rows) >= COUNTERFACTUAL_MINIMUM_TOTAL
        and counter_upper <= COUNTERFACTUAL_MAXIMUM_RISK
    )
    if not eligible_rows:
        verdict = "NO_FULL_PAGE_SPATIAL_CLAIMS"
    elif baseline_false == 0:
        verdict = "FULL_PAGE_BASELINE_TOO_CLEAN_TO_CERTIFY"
    elif not tenfold_bound:
        verdict = "FULL_PAGE_BASELINE_INFORMATIVE_TENFOLD_BOUND_NOT_REACHED"
    else:
        verdict = "DEVELOPMENT_FULL_PAGE_TENFOLD_SIGNAL"

    verifier_times = [
        row["verifier"]["runtime_seconds"] * 1000.0
        for row in eligible_rows
        if row["verifier"]["runtime_seconds"] > 0
    ]
    page_ocr_times = [
        row["page"]["ocr"]["wall_seconds"] for row in observations
    ]
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol": manifest["protocol"],
        "execution": {
            "unique_physical_locations": len(observations),
            "full_pages_rendered": len(observations),
            "full_pages_ocrd": len(observations),
            "eligible_equal_length_spatial_claims": len(eligible_rows),
            "institutions_with_eligible_claims": len(
                {row["institution_code"] for row in eligible_rows}
            ),
            "eligibility_reasons": dict(sorted(reason_counts.items())),
        },
        "baseline": {
            "claims": len(eligible_rows),
            "false_predictions": baseline_false,
            "observed_error_rate": (
                baseline_false / len(eligible_rows) if eligible_rows else None
            ),
            "simultaneous_95pct_lower": baseline_lower,
        },
        "verifier": {
            "accepted": len(accepted_rows),
            "false_accepted": accepted_false,
            "observed_false_acceptance_rate": (
                accepted_false / len(accepted_rows)
                if accepted_rows
                else None
            ),
            "simultaneous_95pct_upper": candidate_upper,
            "accepted_coverage_of_eligible_claims": (
                len(accepted_rows) / len(eligible_rows)
                if eligible_rows
                else 0.0
            ),
            "simultaneous_95pct_coverage_lower": coverage_lower,
            "certified_error_reduction_lower": reduction_lower,
            "median_runtime_ms": (
                statistics.median(verifier_times) if verifier_times else None
            ),
            "p95_runtime_ms": p95(verifier_times),
        },
        "counterfactual": {
            "cases": len(eligible_rows),
            "false_accepts": counter_false,
            "rejection_or_abstention_rate": (
                1.0 - counter_false / len(eligible_rows)
                if eligible_rows
                else None
            ),
            "simultaneous_95pct_upper": counter_upper,
        },
        "timing": {
            "median_full_page_tesseract_seconds": statistics.median(
                page_ocr_times
            ),
            "p95_full_page_tesseract_seconds": p95(page_ocr_times),
        },
        "decision": {
            "development_replay_complete": True,
            "tenfold_bound_reached": tenfold_bound,
            "pass_statistical_10x": False,
            "automatic_production_change": False,
            "final_holdout_opened": False,
            "verdict": verdict,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
        "observations": observations,
    }
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )
    return report


def write_outputs(
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    report_path = output_dir / "full_page_spatial_replay.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"{_sha256(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.roots)
    report = evaluate_manifest(manifest, args.output_dir)
    write_outputs(manifest, report, args.output_dir)
    print(
        json.dumps(
            {
                "execution": report["execution"],
                "baseline": report["baseline"],
                "verifier": report["verifier"],
                "counterfactual": report["counterfactual"],
                "timing": report["timing"],
                "decision": report["decision"],
                "stable_payload_sha256": report[
                    "stable_payload_sha256"
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
