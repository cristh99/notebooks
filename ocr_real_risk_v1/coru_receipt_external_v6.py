"""Frozen CORU Receipt evaluator for numeric-consensus-v6.

This module is bundled before CORU `test.json` or `test.zip` is opened. It is
used only if the frozen schema census finds explicit numeric transcriptions and
sufficient power. Candidate construction consumes the complete receipt image;
annotation text and geometry are used only for pre-OCR risk-unit selection and
post-inference scoring.
"""
from __future__ import annotations

import io
import json
import math
import statistics
import time
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from PIL import Image

from .cord_consensus_detector_v4 import (
    cluster_candidates,
    crop_guard_readings,
    resolved_tokens,
    tesseract_numeric_candidates,
)
from .core import canonical_json, mutate_one_digit, p95, sha256_bytes, sha256_file
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .numeric_digit_forest import infer_claim
from .numeric_digit_forest_deterministic import load_frozen_candidate
from .sroie_natural_holdout import (
    crop_box,
    eligibility,
    match_ocr_claim,
    stable_payload,
    tesseract_tokens,
    verify_stable_payload,
)
from .wildreceipt_v6_gate_completion_lab import predict_v6_gate_completion

EVALUATOR_SCHEMA = "ocr-coru-receipt-external-evaluator/6"
PARTITION_REPORT_SCHEMA = "ocr-coru-receipt-partition-report/6"
AGGREGATE_SCHEMA = "ocr-coru-receipt-external-aggregate/6"
ALPHA_PER_LEG = 0.0125
TARGET_REDUCTION = 10.0
MINIMUM_SELECTED = 3000
MINIMUM_ACCEPTED = 900
MINIMUM_COVERAGE_LOWER = 0.25
COUNTERFACTUAL_MAXIMUM_UPPER = 0.01
MAX_UNCOMPRESSED_ARCHIVE_BYTES = 25_000_000_000
SUPPORTED_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}


def normalized_member_name(value: object) -> str:
    raw = str(value or "")
    if not raw or "\\" in raw or "\x00" in raw:
        raise RuntimeError("unsafe or empty CORU ZIP member name")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"unsafe CORU ZIP member path: {raw!r}")
    return path.as_posix()


def safe_image_members(path: Path) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    total = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
    for info in infos:
        name = normalized_member_name(info.filename)
        if name in members:
            raise RuntimeError(f"duplicate CORU ZIP member: {name}")
        if info.flag_bits & 0x1:
            raise RuntimeError(f"encrypted CORU ZIP member: {name}")
        if info.is_dir():
            continue
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise RuntimeError(f"symbolic-link CORU ZIP member: {name}")
        total += int(info.file_size)
        if total > MAX_UNCOMPRESSED_ARCHIVE_BYTES:
            raise RuntimeError("CORU ZIP exceeds frozen uncompressed-byte limit")
        if PurePosixPath(name.lower()).suffix in SUPPORTED_IMAGE_SUFFIXES:
            members[name] = info
    if not members:
        raise RuntimeError("CORU test archive contains no supported images")
    return members


def resolve_image_members(
    selected_records: Sequence[Mapping[str, Any]],
    archive_members: Mapping[str, zipfile.ZipInfo],
) -> list[dict[str, Any]]:
    by_basename: dict[str, list[str]] = {}
    for member in archive_members:
        by_basename.setdefault(PurePosixPath(member).name, []).append(member)
    resolved: list[dict[str, Any]] = []
    used: set[str] = set()
    for record in selected_records:
        requested = normalized_member_name(record["filename"])
        if requested in archive_members:
            member = requested
            method = "exact_path"
        else:
            matches = by_basename.get(PurePosixPath(requested).name, [])
            if len(matches) != 1:
                raise RuntimeError(
                    f"CORU image member is missing or ambiguous: {requested}"
                )
            member = matches[0]
            method = "unique_basename"
        if member in used:
            raise RuntimeError(
                f"multiple CORU selected records resolve to one archive image: {member}"
            )
        used.add(member)
        resolved.append(
            {
                **dict(record),
                "archive_member": member,
                "archive_resolution": method,
            }
        )
    resolved.sort(key=lambda row: (row["archive_member"], row["image_id"]))
    return resolved


def partition_id(record: Mapping[str, Any], partition_count: int) -> int:
    if partition_count <= 0:
        raise ValueError("partition_count must be positive")
    digest = sha256_bytes(
        canonical_json(
            {
                "filename": record["filename"],
                "annotation_id": record["annotation_id"],
                "truth": record["truth"],
                "bbox_xyxy": record["bbox_xyxy"],
            }
        ).encode("utf-8")
    )
    return int(digest[:16], 16) % partition_count


def _candidate_manifest(root: Path) -> dict[str, Any]:
    from .numeric_consensus_candidate_v6_coru import verify_manifest

    payload = json.loads((root / "frozen_candidate.json").read_text(encoding="utf-8"))
    if not verify_manifest(payload):
        raise RuntimeError("CORU v6 candidate stable payload failed")
    if payload.get("candidate_id") != "numeric-consensus-v6-coru-receipt":
        raise RuntimeError("unexpected CORU v6 candidate id")
    if payload.get("decision", {}).get("candidate_frozen_before_coru_schema_opening") is not True:
        raise RuntimeError("CORU v6 candidate was not frozen before schema opening")
    return payload


def load_candidate_bundle(root: Path) -> tuple[dict[str, Any], Any]:
    manifest = _candidate_manifest(root)
    model_candidate, model = load_frozen_candidate(root / "model")
    if model_candidate["model"]["sha256"] != manifest["digit_model"]["model_sha256"]:
        raise RuntimeError("CORU candidate/model SHA-256 mismatch")
    if float(manifest["digit_model"]["threshold"]) != 0.25:
        raise RuntimeError("CORU candidate digit threshold changed")
    if len(model.estimators_) != 500:
        raise RuntimeError("CORU candidate tree count changed")
    return manifest, model


def _decode_image(raw: bytes, member: str) -> Image.Image:
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            image = opened.convert("RGB")
    except Exception as exc:
        raise RuntimeError(f"CORU image cannot be decoded: {member}") from exc
    if image.width <= 0 or image.height <= 0:
        raise RuntimeError(f"CORU image has invalid dimensions: {member}")
    return image


def _clip_bbox(
    bbox: Sequence[object], image: Image.Image
) -> tuple[int, int, int, int]:
    if len(bbox) != 4:
        raise RuntimeError("CORU selected bbox must contain four coordinates")
    try:
        x0, y0, x1, y1 = (float(value) for value in bbox)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("CORU selected bbox is non-numeric") from exc
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise RuntimeError("CORU selected bbox is non-finite")
    clipped = (
        max(0, min(image.width, int(math.floor(x0)))),
        max(0, min(image.height, int(math.floor(y0)))),
        max(0, min(image.width, int(math.ceil(x1)))),
        max(0, min(image.height, int(math.ceil(y1)))),
    )
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise RuntimeError("CORU selected bbox has no image overlap")
    return clipped


def evaluate_record(
    image: Image.Image,
    record: Mapping[str, Any],
    model: Any,
    detector_configuration: Mapping[str, Any],
) -> dict[str, Any]:
    truth = str(record["truth"])
    bbox = _clip_bbox(record["bbox_xyxy"], image)
    counterfactual = mutate_one_digit(
        truth,
        (
            f"{record['filename']}:{record['annotation_id']}:"
            f"{record['selection_rank_sha256']}"
        ),
    )

    baseline_tokens, baseline_runtime = tesseract_tokens(image)
    baseline_matched = match_ocr_claim(bbox, baseline_tokens)
    baseline_claim, baseline_eligible, baseline_reason = eligibility(
        truth, baseline_matched
    )

    raw_candidates: list[dict[str, Any]] = []
    psm_runtime: dict[str, Any] = {}
    for psm in detector_configuration["psms"]:
        candidates, runtime = tesseract_numeric_candidates(image, int(psm))
        raw_candidates.extend(candidates)
        psm_runtime[str(psm)] = runtime
    clusters = cluster_candidates(raw_candidates)
    resolved = resolved_tokens(clusters, detector_configuration)
    matched = match_ocr_claim(bbox, resolved)
    claim, eligible, reason = eligibility(truth, matched)

    prediction = ""
    minimum_probability: float | None = None
    forest_accepted = False
    guard: dict[str, Any] | None = None
    crop_sha256: str | None = None
    crop_coordinates: list[int] | None = None
    final_prediction: str | None = None
    forest_seconds = 0.0
    if eligible:
        box = crop_box(image, matched["bbox"], margin=2)
        crop_coordinates = list(box)
        crop = image.crop(box)
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG", optimize=False)
        crop_sha256 = sha256_bytes(buffer.getvalue())
        started = time.perf_counter()
        decision = infer_claim(model, crop, claim, threshold=0.25)
        forest_seconds = time.perf_counter() - started
        prediction = str(decision.get("prediction") or "")
        minimum_probability = float(
            decision.get("minimum_mean_probability") or 0.0
        )
        forest_accepted = bool(decision.get("accepted"))
        guard = crop_guard_readings(crop)
        policy_row = {
            "candidate": {
                "eligible": True,
                "claim": claim,
                "prediction": prediction,
                "minimum_mean_probability": minimum_probability,
                "forest_accepted": forest_accepted,
                "matched": matched,
                "guard": guard,
            }
        }
        final_prediction = predict_v6_gate_completion(policy_row)

    return {
        "truth": truth,
        "counterfactual_claim": counterfactual,
        "bbox_xyxy": list(bbox),
        "baseline": {
            "claim": baseline_claim,
            "eligible": baseline_eligible,
            "reason": baseline_reason,
            "claim_correct": bool(
                baseline_eligible and baseline_claim == truth
            ),
            "matched": baseline_matched,
            "runtime": baseline_runtime,
        },
        "candidate": {
            "claim": claim,
            "eligible": eligible,
            "reason": reason,
            "matched": matched,
            "prediction": prediction,
            "minimum_mean_probability": minimum_probability,
            "forest_accepted": forest_accepted,
            "guard": guard,
            "final_prediction": final_prediction,
            "accepted": final_prediction is not None,
            "correct_accept": final_prediction == truth,
            "false_accept": bool(
                final_prediction is not None and final_prediction != truth
            ),
            "counterfactual_output_collision": bool(
                final_prediction is not None
                and final_prediction == counterfactual
            ),
            "crop_box": crop_coordinates,
            "crop_sha256": crop_sha256,
            "forest_seconds": forest_seconds,
            "psm_runtime": psm_runtime,
        },
    }


def exact_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    baseline = [row for row in selected if row["baseline"]["eligible"]]
    baseline_false = sum(
        not row["baseline"]["claim_correct"] for row in baseline
    )
    accepted = [row for row in selected if row["candidate"]["accepted"]]
    accepted_false = sum(row["candidate"]["false_accept"] for row in accepted)
    counterfactual_false = sum(
        row["candidate"]["counterfactual_output_collision"]
        for row in selected
    )
    baseline_lower = (
        clopper_pearson_lower(
            baseline_false, len(baseline), ALPHA_PER_LEG
        )
        if baseline
        else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(
            accepted_false, len(accepted), ALPHA_PER_LEG
        )
        if accepted
        else 1.0
    )
    coverage_lower = (
        clopper_pearson_lower(
            len(accepted), len(selected), ALPHA_PER_LEG
        )
        if selected
        else 0.0
    )
    counterfactual_upper = (
        clopper_pearson_upper(
            counterfactual_false, len(selected), ALPHA_PER_LEG
        )
        if selected
        else 1.0
    )
    reduction_lower = (
        baseline_lower / candidate_upper if candidate_upper > 0 else None
    )
    passed = bool(
        len(selected) >= MINIMUM_SELECTED
        and baseline_false > 0
        and len(accepted) >= MINIMUM_ACCEPTED
        and coverage_lower >= MINIMUM_COVERAGE_LOWER
        and candidate_upper <= baseline_lower / TARGET_REDUCTION
        and counterfactual_upper <= COUNTERFACTUAL_MAXIMUM_UPPER
    )
    return {
        "selected": len(selected),
        "baseline_eligible": len(baseline),
        "baseline_false": baseline_false,
        "accepted": len(accepted),
        "accepted_false": accepted_false,
        "counterfactual_false": counterfactual_false,
        "baseline_lower": baseline_lower,
        "candidate_upper": candidate_upper,
        "coverage_lower": coverage_lower,
        "counterfactual_upper": counterfactual_upper,
        "reduction_lower": reduction_lower,
        "pass": passed,
    }
