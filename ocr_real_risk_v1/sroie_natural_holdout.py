"""External natural-scan OCR holdout on the annotated ICDAR2019 SROIE data.

The verifier and all thresholds are frozen before this dataset is executed.
Exactly one eligible numeric annotation is selected per receipt by SHA-256
before Tesseract runs. Tesseract receives the full natural receipt image; the
verifier receives only the spatially matched Tesseract token box. Expert
annotation boxes are used for selection, matching, and diagnostic crops only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import statistics
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow.parquet as pq
import pytesseract
from PIL import Image
from pytesseract import Output

from .core import canonical_json, mutate_one_digit, p95, sha256_bytes, sha256_file
from .isolated_crop import isolated_native_word_box
from .pixel_digit_alignment import PixelDigitAligner

DATASET_REPO = "jsdnrs/ICDAR2019-SROIE"
DATASET_REVISION = "bffe40c26759f3376ec2b3ae9031dbba54cd587c"
DATASET_LICENSE = "CC-BY-4.0"
DATASET_EXPECTED_ROWS = {"train": 626, "test": 361}
DATASET_PARQUET_SHA256 = {
    "train": "b18c16b4d8481e5e4537a1700e4616907fe4acd92d6362a7e430b0e866213887",
    "test": "04f8f31b45944cc6e6459a7a95c851a721fc93ffec0a5c29ece9ded734a684c2",
}
MANIFEST_SCHEMA = "ocr-sroie-natural-numeric-manifest/1"
REPORT_SCHEMA = "ocr-sroie-natural-numeric-split/1"
OCR_LANGUAGE = "eng"
OCR_PSM = 3
OCR_TIMEOUT_SECONDS = 90
MATCH_MINIMUM_TRUTH_COVERAGE = 0.35
ELIGIBILITY_MINIMUM_TRUTH_COVERAGE = 0.50
MIN_DIGITS = 4
MAX_DIGITS = 12
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
_CURRENCY_PREFIX_RE = re.compile(
    r"^(?:RM|MYR|USD|US\$|\$)\s*:?\s*",
    re.IGNORECASE,
)
_NUMERIC_PATTERNS = (
    re.compile(r"^[+-]?\d+$"),
    re.compile(r"^[+-]?\d+[.,]\d+$"),
    re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?$"),
    re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?$"),
    re.compile(r"^\d+(?:/\d+)+$"),
    re.compile(r"^\d+(?:-\d+)+$"),
    re.compile(r"^\d+(?:\s+\d+)+$"),
)
_NON_DIGIT_RE = re.compile(r"\D+")
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_numeric_region(text: str) -> str | None:
    """Canonicalize one self-contained numeric annotation region."""
    value = unicodedata.normalize("NFKC", str(text or "")).strip().upper()
    value = _CURRENCY_PREFIX_RE.sub("", value)
    value = value.strip(" \t\r\n:;#()[]{}")
    if not value or not any(pattern.fullmatch(value) for pattern in _NUMERIC_PATTERNS):
        return None
    digits = _NON_DIGIT_RE.sub("", value)
    if not MIN_DIGITS <= len(digits) <= MAX_DIGITS:
        return None
    if _YEAR_RE.fullmatch(digits):
        return None
    if len(digits) >= 6 and len(set(digits)) == 1:
        return None
    return digits


def normalized_company(value: object, fallback: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = _NON_ALNUM_RE.sub("", text.upper())
    return text[:120] or f"KEY:{fallback}"


def image_bytes_from_row(row: Mapping[str, Any]) -> bytes:
    image = row.get("image")
    if isinstance(image, Mapping):
        payload = image.get("bytes")
        if isinstance(payload, (bytes, bytearray, memoryview)):
            return bytes(payload)
    if isinstance(image, (bytes, bytearray, memoryview)):
        return bytes(image)
    raise RuntimeError("SROIE parquet row does not contain embedded image bytes")


def iter_parquet_rows(path: Path, *, batch_size: int = 8) -> Iterable[tuple[int, dict[str, Any]]]:
    parquet = pq.ParquetFile(path)
    row_index = 0
    for batch in parquet.iter_batches(batch_size=batch_size):
        for row in batch.to_pylist():
            yield row_index, row
            row_index += 1


def selection_rank(
    *, split: str, key: str, image_sha256: str, bbox: Sequence[int], truth: str
) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "dataset_revision": DATASET_REVISION,
                "split": split,
                "key": key,
                "image_sha256": image_sha256,
                "bbox": [int(value) for value in bbox],
                "truth": truth,
            }
        ).encode("utf-8")
    )


def select_numeric_annotation(
    *,
    split: str,
    key: str,
    image_sha256: str,
    words: Sequence[object],
    bboxes: Sequence[Sequence[object]],
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    if len(words) != len(bboxes):
        raise RuntimeError("SROIE words and bboxes are not one-to-one")
    candidates: dict[tuple[str, tuple[int, int, int, int]], dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for word, raw_bbox in zip(words, bboxes, strict=True):
        truth = canonical_numeric_region(str(word or ""))
        if truth is None:
            counts["annotations_outside_numeric_scope"] += 1
            continue
        try:
            bbox = tuple(int(value) for value in raw_bbox)
        except (TypeError, ValueError):
            raise RuntimeError("SROIE bbox contains a non-integer coordinate") from None
        if len(bbox) != 4 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise RuntimeError("SROIE bbox is malformed or empty")
        counts["numeric_annotations_in_scope"] += 1
        rank = selection_rank(
            split=split,
            key=key,
            image_sha256=image_sha256,
            bbox=bbox,
            truth=truth,
        )
        candidates[(truth, bbox)] = {
            "truth": truth,
            "annotation_text": str(word),
            "bbox": list(bbox),
            "selection_rank_sha256": rank,
        }
    if not candidates:
        return None, dict(counts)
    selected = min(
        candidates.values(),
        key=lambda row: (
            str(row["selection_rank_sha256"]),
            str(row["truth"]),
            tuple(row["bbox"]),
        ),
    )
    counts["unique_numeric_candidates"] = len(candidates)
    return selected, dict(counts)


def stable_payload(value: Mapping[str, Any], hash_field: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(hash_field, None)
    result[hash_field] = sha256_bytes(canonical_json(result).encode("utf-8"))
    return result


def verify_stable_payload(value: Mapping[str, Any], hash_field: str) -> bool:
    expected = str(value.get(hash_field) or "")
    payload = dict(value)
    payload.pop(hash_field, None)
    return expected == sha256_bytes(canonical_json(payload).encode("utf-8"))


def build_manifest(parquet_path: Path, split: str) -> dict[str, Any]:
    if split not in DATASET_EXPECTED_ROWS:
        raise ValueError(f"unsupported SROIE split: {split}")
    observed_parquet_sha = sha256_path(parquet_path)
    expected_parquet_sha = DATASET_PARQUET_SHA256[split]
    if observed_parquet_sha != expected_parquet_sha:
        raise RuntimeError(f"SROIE {split} parquet hash mismatch: {observed_parquet_sha}")

    records: list[dict[str, Any]] = []
    census: Counter[str] = Counter()
    key_set: set[str] = set()
    image_hashes: Counter[str] = Counter()
    truth_lengths: Counter[int] = Counter()
    for row_index, row in iter_parquet_rows(parquet_path):
        census["rows"] += 1
        key = str(row.get("key") or "").strip()
        if not key or key in key_set:
            raise RuntimeError("SROIE split contains an empty or duplicate key")
        key_set.add(key)
        image_bytes = image_bytes_from_row(row)
        image_sha = sha256_bytes(image_bytes)
        image_hashes[image_sha] += 1
        with Image.open(io.BytesIO(image_bytes)) as opened:
            width, height = opened.size
        image_size = row.get("image_size") or {}
        if (
            int(image_size.get("width") or 0) != width
            or int(image_size.get("height") or 0) != height
        ):
            raise RuntimeError("SROIE image_size does not match embedded image")
        selected, counts = select_numeric_annotation(
            split=split,
            key=key,
            image_sha256=image_sha,
            words=list(row.get("words") or []),
            bboxes=list(row.get("bboxes") or []),
        )
        census.update(counts)
        if selected is None:
            census["rows_without_numeric_candidate"] += 1
            continue
        bbox = [int(value) for value in selected["bbox"]]
        if bbox[0] < 0 or bbox[1] < 0 or bbox[2] > width or bbox[3] > height:
            raise RuntimeError("selected SROIE bbox lies outside the image")
        entities = row.get("entities") or {}
        company = str(entities.get("company") or "")
        truth_lengths[len(str(selected["truth"]))] += 1
        records.append(
            {
                "split": split,
                "row_index": row_index,
                "key": key,
                "image_sha256": image_sha,
                "image_width": width,
                "image_height": height,
                "company": company,
                "company_group": normalized_company(company, key),
                **selected,
                "counterfactual_claim": mutate_one_digit(
                    str(selected["truth"]),
                    f"{DATASET_REVISION}:{split}:{key}:{selected['selection_rank_sha256']}",
                ),
            }
        )
        census["rows_with_selected_numeric_location"] += 1

    expected_rows = DATASET_EXPECTED_ROWS[split]
    if census["rows"] != expected_rows:
        raise RuntimeError(
            f"SROIE {split} row count changed: {census['rows']} != {expected_rows}"
        )
    records.sort(key=lambda row: (int(row["row_index"]), str(row["key"])))
    selected_keys = [str(row["key"]) for row in records]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "dataset": {
            "repo": DATASET_REPO,
            "revision": DATASET_REVISION,
            "license": DATASET_LICENSE,
            "split": split,
            "parquet_sha256": observed_parquet_sha,
            "expected_rows": expected_rows,
        },
        "protocol": {
            "risk_unit": "one pre-OCR SHA-selected numeric annotation per receipt",
            "numeric_scope": (
                "one self-contained 4-12 digit expression after declared currency/"
                "separator normalization; standalone years and repeated-digit junk excluded"
            ),
            "selection_uses_ocr": False,
            "page_input": "entire original natural receipt image",
            "tesseract": {
                "language": OCR_LANGUAGE,
                "oem": 1,
                "psm": OCR_PSM,
                "timeout_seconds": OCR_TIMEOUT_SECONDS,
            },
            "spatial_match_minimum_truth_coverage": MATCH_MINIMUM_TRUTH_COVERAGE,
            "eligibility_minimum_truth_coverage": ELIGIBILITY_MINIMUM_TRUTH_COVERAGE,
            "eligibility_equal_canonical_length_required": True,
            "primary_verifier_crop": "matched Tesseract token bbox plus 2 pixels",
            "truth_bbox_primary_verifier_use": False,
            "truth_bbox_diagnostic_use": True,
            "verifier_thresholds_frozen_before_dataset_execution": True,
            "both_published_splits_used_as_one_external_benchmark": True,
        },
        "census": {
            **dict(sorted(census.items())),
            "unique_keys": len(key_set),
            "unique_images": len(image_hashes),
            "duplicate_image_associations": sum(
                count - 1 for count in image_hashes.values() if count > 1
            ),
            "selected_key_set_sha256": sha256_bytes(
                canonical_json(selected_keys).encode("utf-8")
            ),
            "truth_length_distribution": {
                str(key): value for key, value in sorted(truth_lengths.items())
            },
        },
        "records": records,
    }
    return stable_payload(manifest, "manifest_sha256")


def _canonical_digits(value: object) -> str:
    return _NON_DIGIT_RE.sub("", str(value or ""))


def tesseract_tokens(image: Image.Image) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    os.environ["OMP_THREAD_LIMIT"] = "1"
    started = time.perf_counter()
    try:
        data = pytesseract.image_to_data(
            image,
            lang=OCR_LANGUAGE,
            config=f"--oem 1 --psm {OCR_PSM}",
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
    tokens: list[dict[str, Any]] = []
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
        tokens.append(
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
    return tokens, {
        "wall_seconds": elapsed,
        "numeric_tokens": len(tokens),
        "invalid_numeric_boxes_filtered": invalid_boxes,
        "timeout": timeout,
    }


def overlap_metrics(
    truth_bbox: Sequence[float], token_bbox: Sequence[float]
) -> tuple[float, float, float, float]:
    tx0, ty0, tx1, ty1 = map(float, truth_bbox)
    bx0, by0, bx1, by1 = map(float, token_bbox)
    ix0, iy0 = max(tx0, bx0), max(ty0, by0)
    ix1, iy1 = min(tx1, bx1), min(ty1, by1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    truth_area = max(1e-9, (tx1 - tx0) * (ty1 - ty0))
    token_area = max(1e-9, (bx1 - bx0) * (by1 - by0))
    union = truth_area + token_area - intersection
    truth_center = ((tx0 + tx1) / 2.0, (ty0 + ty1) / 2.0)
    token_center = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
    distance = math.hypot(
        token_center[0] - truth_center[0], token_center[1] - truth_center[1]
    )
    return intersection / union, intersection / truth_area, intersection / token_area, distance


def match_ocr_claim(
    truth_bbox: Sequence[float], tokens: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    tx0, ty0, tx1, ty1 = map(float, truth_bbox)
    truth_center = ((tx0 + tx1) / 2.0, (ty0 + ty1) / 2.0)
    ranked: list[tuple[float, float, str, Mapping[str, Any], dict[str, float]]] = []
    for token in tokens:
        bbox = token.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        digits = _canonical_digits(token.get("text"))
        if not digits:
            continue
        iou, truth_cover, token_cover, distance = overlap_metrics(truth_bbox, bbox)
        bx0, by0, bx1, by1 = map(float, bbox)
        contains_center = (
            bx0 <= truth_center[0] <= bx1 and by0 <= truth_center[1] <= by1
        )
        if truth_cover < MATCH_MINIMUM_TRUTH_COVERAGE and not contains_center:
            continue
        score = 3.0 * truth_cover + token_cover + 0.5 * iou - 0.001 * distance
        ranked.append(
            (
                score,
                float(token.get("confidence") or -1.0),
                digits,
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
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    _, _, _, token, metrics = ranked[0]
    result = dict(token)
    result["match"] = metrics
    return result


def eligibility(
    truth: str, matched: Mapping[str, Any] | None
) -> tuple[str, bool, str]:
    if matched is None:
        return "", False, "NO_SPATIAL_MATCH"
    claim = _canonical_digits(matched.get("text"))
    if not claim:
        return "", False, "EMPTY_CLAIM"
    if len(claim) != len(truth):
        return claim, False, "LENGTH_MISMATCH_OUTSIDE_SUBSTITUTION_SCOPE"
    coverage = float((matched.get("match") or {}).get("truth_coverage") or 0.0)
    if coverage < ELIGIBILITY_MINIMUM_TRUTH_COVERAGE:
        return claim, False, "LOW_SPATIAL_COVERAGE"
    return claim, True, "ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM"


def crop_box(
    image: Image.Image, bbox: Sequence[float], margin: int = 2
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = map(float, bbox)
    box = (
        max(0, math.floor(x0) - margin),
        max(0, math.floor(y0) - margin),
        min(image.width, math.ceil(x1) + margin),
        min(image.height, math.ceil(y1) + margin),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("empty crop")
    return box


def _status(decision: Any) -> str:
    status = getattr(decision, "status", "")
    return str(getattr(status, "value", status))


def _prediction(decision: Any) -> str:
    return str(getattr(decision, "predicted", ""))


def evaluate_split(
    parquet_path: Path,
    manifest: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    if not verify_stable_payload(manifest, "manifest_sha256"):
        raise RuntimeError("SROIE manifest hash verification failed")
    split = str(manifest["dataset"]["split"])
    records = {int(row["row_index"]): dict(row) for row in manifest["records"]}
    if len(records) != len(manifest["records"]):
        raise RuntimeError("SROIE manifest contains duplicate row indices")
    crops_dir = output_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    aligner = PixelDigitAligner()
    _ = aligner._bank  # type: ignore[attr-defined]
    observations: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    processed_selected_rows: set[int] = set()

    for row_index, row in iter_parquet_rows(parquet_path):
        record = records.get(row_index)
        if record is None:
            continue
        processed_selected_rows.add(row_index)
        key = str(row.get("key") or "")
        if key != record["key"]:
            raise RuntimeError("SROIE row key changed after manifest sealing")
        image_bytes = image_bytes_from_row(row)
        image_sha = sha256_bytes(image_bytes)
        if image_sha != record["image_sha256"]:
            raise RuntimeError("SROIE image changed after manifest sealing")
        selected, _ = select_numeric_annotation(
            split=split,
            key=key,
            image_sha256=image_sha,
            words=list(row.get("words") or []),
            bboxes=list(row.get("bboxes") or []),
        )
        if selected is None or any(
            selected[field] != record[field]
            for field in ("truth", "bbox", "selection_rank_sha256")
        ):
            raise RuntimeError("SROIE selection changed after manifest sealing")
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGB")
        tokens, runtime = tesseract_tokens(image)
        matched = match_ocr_claim(record["bbox"], tokens)
        claim, eligible, reason = eligibility(str(record["truth"]), matched)
        reasons[reason] += 1
        correct = eligible and claim == record["truth"]
        if eligible:
            source = "tesseract_matched_bbox"
            box = crop_box(image, matched["bbox"], margin=2)
        else:
            source = "truth_bbox_diagnostic_only"
            box = isolated_native_word_box(
                record["bbox"],
                (float(image.width), float(image.height)),
                image.size,
            )
        crop = image.crop(box)
        evidence_key = sha256_bytes(
            canonical_json(
                {
                    "image_sha256": image_sha,
                    "bbox": record["bbox"],
                    "truth": record["truth"],
                }
            ).encode("utf-8")
        )
        retained = crops_dir / f"{evidence_key}.png"
        crop.save(retained, optimize=False)
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
        observation = {
            "evidence_key": evidence_key,
            "split": split,
            "row_index": row_index,
            "key": key,
            "image_sha256": image_sha,
            "image_width": image.width,
            "image_height": image.height,
            "company": record["company"],
            "company_group": record["company_group"],
            "truth": record["truth"],
            "annotation_text": record["annotation_text"],
            "bbox": record["bbox"],
            "selection_rank_sha256": record["selection_rank_sha256"],
            "tesseract": {
                "claim": claim,
                "eligible": eligible,
                "eligibility_reason": reason,
                "claim_correct": correct,
                "matched": matched,
                "page_runtime": runtime,
            },
            "verifier": {
                "crop_source": source,
                "crop_box": list(box),
                "crop_file": f"crops/{retained.name}",
                "crop_sha256": sha256_file(retained),
                "status": verifier_status,
                "prediction": verifier_prediction,
                "accepted": accepted,
                "correct_accept": accepted and correct,
                "false_accept": accepted and not correct,
                "runtime_seconds": verifier_seconds,
            },
            "counterfactual": {
                "claim": record["counterfactual_claim"],
                "status": counter_status,
                "prediction": counter_prediction,
                "false_accept": eligible and counter_status == "ALIGNED",
                "runtime_seconds": counter_seconds,
            },
        }
        observations.append(observation)
        print(
            json.dumps(
                {
                    "split": split,
                    "selected_processed": len(observations),
                    "selected_total": len(records),
                    "eligible": sum(item["tesseract"]["eligible"] for item in observations),
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

    if processed_selected_rows != set(records):
        missing = sorted(set(records) - processed_selected_rows)
        raise RuntimeError(f"SROIE selected rows were not evaluated: {missing[:10]}")
    observations.sort(key=lambda row: (int(row["row_index"]), str(row["key"])))
    eligible_rows = [row for row in observations if row["tesseract"]["eligible"]]
    accepted_rows = [row for row in eligible_rows if row["verifier"]["accepted"]]
    verifier_times = [
        row["verifier"]["runtime_seconds"] * 1000.0
        for row in eligible_rows
        if row["verifier"]["runtime_seconds"] > 0
    ]
    page_times = [row["tesseract"]["page_runtime"]["wall_seconds"] for row in observations]
    report = {
        "schema": REPORT_SCHEMA,
        "dataset": dict(manifest["dataset"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol": dict(manifest["protocol"]),
        "execution": {
            "rows": manifest["census"]["rows"],
            "selected_locations": len(observations),
            "eligible_claims": len(eligible_rows),
            "accepted": len(accepted_rows),
            "eligibility_reasons": dict(sorted(reasons.items())),
            "ocr_timeouts": sum(
                row["tesseract"]["page_runtime"]["timeout"] for row in observations
            ),
        },
        "descriptive": {
            "baseline_errors": sum(
                not row["tesseract"]["claim_correct"] for row in eligible_rows
            ),
            "verifier_false_accepts": sum(
                row["verifier"]["false_accept"] for row in accepted_rows
            ),
            "counterfactual_false_accepts": sum(
                row["counterfactual"]["false_accept"] for row in observations
            ),
            "accepted_coverage_of_selected": (
                len(accepted_rows) / len(observations) if observations else 0.0
            ),
            "median_full_image_tesseract_seconds": (
                statistics.median(page_times) if page_times else None
            ),
            "p95_full_image_tesseract_seconds": p95(page_times),
            "median_verifier_ms": (
                statistics.median(verifier_times) if verifier_times else None
            ),
            "p95_verifier_ms": p95(verifier_times),
        },
        "decision": {
            "split_execution_complete": True,
            "aggregate_certificate_required": True,
            "pass_statistical_10x": False,
            "automatic_production_change": False,
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
    return stable_payload(report, "stable_payload_sha256")


def write_split_outputs(
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    report_path = output_dir / "split_report.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "ATTRIBUTION.md").write_text(
        "# Attribution\n\n"
        "Numeric crops derive from `jsdnrs/ICDAR2019-SROIE`, revision "
        f"`{DATASET_REVISION}`, distributed under CC-BY-4.0. The source adapts "
        "the ICDAR2019 SROIE scanned-receipt dataset. This artifact adds a "
        "deterministic numeric selection and OCR/verifier evaluation; it does not "
        "redistribute full receipt images.\n",
        encoding="utf-8",
    )
    lines = [
        f"{sha256_path(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", required=True, type=Path)
    parser.add_argument("--split", required=True, choices=tuple(DATASET_EXPECTED_ROWS))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    shutil.rmtree(args.output_dir, ignore_errors=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(args.parquet, args.split)
    manifest_path = args.output_dir / "manifest.pre_ocr.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = evaluate_split(args.parquet, manifest, args.output_dir)
    manifest_path.unlink()
    write_split_outputs(manifest, report, args.output_dir)
    print(
        json.dumps(
            {
                "dataset": report["dataset"],
                "manifest_census": manifest["census"],
                "execution": report["execution"],
                "descriptive": report["descriptive"],
                "decision": report["decision"],
                "manifest_sha256": manifest["manifest_sha256"],
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
