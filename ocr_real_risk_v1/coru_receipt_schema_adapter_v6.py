"""Frozen fail-closed schema adapter for CORU Receipt annotations.

The adapter is intentionally executed only after numeric-consensus-v6 is
frozen. It opens `labels.txt` and `test.json`, but never the 1.06 GB image
archive. It supports deterministic COCO-style object-detection JSON only and
selects a numeric risk unit only when an annotation contains an explicit text
transcription. Category labels alone are never treated as OCR truth.
"""
from __future__ import annotations

import json
import math
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import canonical_json, sha256_bytes, sha256_file
from .sroie_natural_holdout import stable_payload

DATASET_ID = "abdoelsayed/CORU"
DATASET_REVISION = "c3c4b97b232bbe03046c78a974f516d439c1124e"
COMPONENT = "Receipt"
ADAPTER_SCHEMA = "ocr-coru-receipt-schema-adapter/6"
CENSUS_SCHEMA = "ocr-coru-receipt-schema-census/6"
TRANSCRIPTION_FIELDS = (
    "transcription",
    "text",
    "ocr_text",
    "label_text",
    "value",
    "content",
    "caption",
)
IMAGE_FILENAME_FIELDS = ("file_name", "filename", "path", "name")
MIN_DIGITS = 4
MAX_DIGITS = 12
YEAR_MIN = 1900
YEAR_MAX = 2099
EXPECTED_TEST_JSON_SHA256 = (
    "f9bd21061515ca79ce1ceecf0837faa8c1f418eaa406fc6d38c6eff012ee6ab7"
)
EXPECTED_TEST_JSON_BYTES = 5_022_111
EXPECTED_LABELS_SHA256 = (
    "4d7ee3c5720620f15791980c30514e110a89c64f40c6b1f9a296b2523ba46555"
)
EXPECTED_LABELS_BYTES = 31
EXPECTED_TEST_ARCHIVE_SHA256 = (
    "351d1c5a2ab1ef12399787679563fbc9922a8d18e0f6296e16d7db0e0a4f7f41"
)
EXPECTED_TEST_ARCHIVE_BYTES = 1_057_581_808
MINIMUM_SELECTED = 3000
MINIMUM_ACCEPTED = 900
DEVELOPMENT_ACCEPTANCE_RATE = 472 / 1720


def canonical_numeric_text(value: object) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return None
    digits: list[str] = []
    for character in text:
        if "0" <= character <= "9":
            digits.append(character)
            continue
        category = unicodedata.category(character)
        if (
            character.isspace()
            or character in ",.:'’`/-_()[]{}+"
            or category in {"Sc", "Pd", "Po", "Ps", "Pe"}
        ):
            continue
        return None
    canonical = "".join(digits)
    if not MIN_DIGITS <= len(canonical) <= MAX_DIGITS:
        return None
    if len(set(canonical)) == 1:
        return None
    if len(canonical) == 4 and YEAR_MIN <= int(canonical) <= YEAR_MAX:
        return None
    return canonical


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise RuntimeError(f"CORU annotation JSON missing: {path}")
    raw = path.read_bytes()
    if sha256_bytes(raw) != EXPECTED_TEST_JSON_SHA256:
        raise RuntimeError("CORU test.json SHA-256 changed")
    if len(raw) != EXPECTED_TEST_JSON_BYTES:
        raise RuntimeError("CORU test.json size changed")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("CORU test.json is not valid UTF-8 JSON") from exc


def _load_labels(path: Path) -> list[str]:
    if not path.is_file():
        raise RuntimeError(f"CORU labels file missing: {path}")
    raw = path.read_bytes()
    if sha256_bytes(raw) != EXPECTED_LABELS_SHA256:
        raise RuntimeError("CORU labels.txt SHA-256 changed")
    if len(raw) != EXPECTED_LABELS_BYTES:
        raise RuntimeError("CORU labels.txt size changed")
    try:
        labels = [
            line.strip()
            for line in raw.decode("utf-8-sig").splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as exc:
        raise RuntimeError("CORU labels.txt is not valid UTF-8") from exc
    if not labels or len(set(labels)) != len(labels):
        raise RuntimeError("CORU labels.txt is empty or contains duplicates")
    return labels


def _numeric_bbox(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise RuntimeError("COCO bbox must be a four-number sequence")
    values = list(value)
    if len(values) != 4:
        raise RuntimeError("COCO bbox must contain exactly four numbers")
    try:
        x, y, width, height = (float(item) for item in values)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("COCO bbox contains a non-numeric value") from exc
    if not all(math.isfinite(item) for item in (x, y, width, height)):
        raise RuntimeError("COCO bbox contains a non-finite value")
    if width <= 0 or height <= 0:
        raise RuntimeError("COCO bbox has non-positive extent")
    return x, y, x + width, y + height


def _explicit_transcription(annotation: Mapping[str, Any]) -> tuple[str, str] | None:
    present = [field for field in TRANSCRIPTION_FIELDS if field in annotation]
    if not present:
        return None
    normalized = {
        field: unicodedata.normalize(
            "NFKC", str(annotation.get(field) or "")
        ).strip()
        for field in present
    }
    nonempty = {value for value in normalized.values() if value}
    if len(nonempty) > 1:
        raise RuntimeError(
            "CORU annotation has conflicting explicit transcription fields"
        )
    if not nonempty:
        return None
    selected_field = next(
        field for field in TRANSCRIPTION_FIELDS if normalized.get(field)
    )
    return selected_field, normalized[selected_field]


def _image_filename(image: Mapping[str, Any]) -> str:
    present = [field for field in IMAGE_FILENAME_FIELDS if image.get(field)]
    if not present:
        raise RuntimeError("CORU COCO image lacks a filename field")
    values = {str(image[field]).strip() for field in present}
    if len(values) != 1:
        raise RuntimeError("CORU COCO image has conflicting filename fields")
    filename = next(iter(values))
    if not filename or "\x00" in filename or filename.startswith("/"):
        raise RuntimeError("CORU COCO image filename is unsafe")
    parts = Path(filename).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError("CORU COCO image filename is unsafe")
    return filename.replace("\\", "/")


def _schema_fingerprint(payload: Mapping[str, Any]) -> dict[str, Any]:
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    annotations = (
        payload.get("annotations")
        if isinstance(payload.get("annotations"), list)
        else []
    )
    categories = (
        payload.get("categories")
        if isinstance(payload.get("categories"), list)
        else []
    )
    return {
        "top_level_keys": sorted(str(key) for key in payload),
        "first_image_keys": (
            sorted(str(key) for key in images[0])
            if images and isinstance(images[0], Mapping)
            else []
        ),
        "first_annotation_keys": (
            sorted(str(key) for key in annotations[0])
            if annotations and isinstance(annotations[0], Mapping)
            else []
        ),
        "first_category_keys": (
            sorted(str(key) for key in categories[0])
            if categories and isinstance(categories[0], Mapping)
            else []
        ),
        "image_count": len(images),
        "annotation_count": len(annotations),
        "category_count": len(categories),
    }


def census_coco(
    payload: Any,
    labels: Sequence[str],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {
            "supported_schema": False,
            "schema_status": "TOP_LEVEL_JSON_IS_NOT_AN_OBJECT",
            "selected_records": [],
            "schema_fingerprint": {
                "top_level_type": type(payload).__name__,
            },
        }
    fingerprint = _schema_fingerprint(payload)
    if not all(
        isinstance(payload.get(field), list)
        for field in ("images", "annotations", "categories")
    ):
        return {
            "supported_schema": False,
            "schema_status": "NOT_COCO_IMAGES_ANNOTATIONS_CATEGORIES",
            "selected_records": [],
            "schema_fingerprint": fingerprint,
        }

    images: dict[str, dict[str, Any]] = {}
    filenames: set[str] = set()
    for raw in payload["images"]:
        if not isinstance(raw, Mapping) or "id" not in raw:
            raise RuntimeError("CORU COCO image record is malformed")
        image_id = str(raw["id"])
        if image_id in images:
            raise RuntimeError(f"duplicate CORU COCO image id: {image_id}")
        filename = _image_filename(raw)
        if filename in filenames:
            raise RuntimeError(f"duplicate CORU COCO filename: {filename}")
        filenames.add(filename)
        images[image_id] = {
            "image_id": image_id,
            "filename": filename,
            "width": raw.get("width"),
            "height": raw.get("height"),
        }

    category_ids: set[str] = set()
    for raw in payload["categories"]:
        if not isinstance(raw, Mapping) or "id" not in raw:
            raise RuntimeError("CORU COCO category record is malformed")
        category_id = str(raw["id"])
        if category_id in category_ids:
            raise RuntimeError(f"duplicate CORU COCO category id: {category_id}")
        category_ids.add(category_id)

    counts: Counter[str] = Counter()
    fields: Counter[str] = Counter()
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    annotation_ids: set[str] = set()
    for index, raw in enumerate(payload["annotations"]):
        if not isinstance(raw, Mapping):
            raise RuntimeError("CORU COCO annotation record is malformed")
        annotation_id = str(raw.get("id", f"index:{index}"))
        if annotation_id in annotation_ids:
            raise RuntimeError(f"duplicate CORU annotation id: {annotation_id}")
        annotation_ids.add(annotation_id)
        image_id = str(raw.get("image_id", ""))
        if image_id not in images:
            raise RuntimeError(
                f"CORU annotation references unknown image: {image_id}"
            )
        if "category_id" in raw and str(raw["category_id"]) not in category_ids:
            raise RuntimeError("CORU annotation references unknown category")
        counts["annotations_total"] += 1
        explicit = _explicit_transcription(raw)
        if explicit is None:
            counts["annotations_without_explicit_transcription"] += 1
            continue
        field, text = explicit
        fields[field] += 1
        counts["annotations_with_explicit_transcription"] += 1
        truth = canonical_numeric_text(text)
        if truth is None:
            counts["explicit_transcriptions_outside_numeric_scope"] += 1
            continue
        bbox = _numeric_bbox(raw.get("bbox"))
        image = images[image_id]
        rank = sha256_bytes(
            canonical_json(
                {
                    "dataset_revision": DATASET_REVISION,
                    "filename": image["filename"],
                    "bbox_xyxy": list(bbox),
                    "truth": truth,
                    "annotation_id": annotation_id,
                }
            ).encode("utf-8")
        )
        candidates[image_id].append(
            {
                "image_id": image_id,
                "filename": image["filename"],
                "annotation_id": annotation_id,
                "category_id": raw.get("category_id"),
                "transcription_field": field,
                "annotation_text": text,
                "truth": truth,
                "bbox_xyxy": list(bbox),
                "selection_rank_sha256": rank,
            }
        )
        counts["numeric_annotations_in_scope"] += 1

    selected: list[dict[str, Any]] = []
    for image_id in sorted(candidates):
        unique: dict[tuple[str, tuple[float, ...]], dict[str, Any]] = {}
        for candidate in candidates[image_id]:
            identity = (
                str(candidate["truth"]),
                tuple(float(value) for value in candidate["bbox_xyxy"]),
            )
            previous = unique.get(identity)
            if previous is None or candidate["selection_rank_sha256"] < previous[
                "selection_rank_sha256"
            ]:
                unique[identity] = candidate
        chosen = min(
            unique.values(),
            key=lambda candidate: (
                str(candidate["selection_rank_sha256"]),
                str(candidate["truth"]),
                tuple(candidate["bbox_xyxy"]),
            ),
        )
        selected.append(chosen)
    selected.sort(key=lambda row: (row["filename"], row["image_id"]))
    status = (
        "SUPPORTED_COCO_WITH_EXPLICIT_NUMERIC_TRANSCRIPTIONS"
        if selected
        else (
            "COCO_WITHOUT_EXPLICIT_TRANSCRIPTION_FIELDS"
            if counts["annotations_with_explicit_transcription"] == 0
            else "COCO_WITHOUT_IN_SCOPE_NUMERIC_TRANSCRIPTIONS"
        )
    )
    return {
        "supported_schema": True,
        "schema_status": status,
        "schema_fingerprint": fingerprint,
        "labels": list(labels),
        "counts": {
            **dict(sorted(counts.items())),
            "images_total": len(images),
            "images_with_numeric_candidate": len(selected),
        },
        "transcription_fields": dict(sorted(fields.items())),
        "selected_records": selected,
        "selected_record_set_sha256": sha256_bytes(
            canonical_json(selected).encode("utf-8")
        ),
    }


def build_census(test_json: Path, labels_path: Path) -> dict[str, Any]:
    payload = _load_json(test_json)
    labels = _load_labels(labels_path)
    schema = census_coco(payload, labels)
    selected = len(schema["selected_records"])
    projected_accepted = selected * DEVELOPMENT_ACCEPTANCE_RATE
    run_archive = bool(
        schema["supported_schema"]
        and schema["schema_status"]
        == "SUPPORTED_COCO_WITH_EXPLICIT_NUMERIC_TRANSCRIPTIONS"
        and selected >= MINIMUM_SELECTED
        and projected_accepted >= MINIMUM_ACCEPTED
    )
    report: dict[str, Any] = {
        "schema": CENSUS_SCHEMA,
        "adapter_schema": ADAPTER_SCHEMA,
        "dataset": {
            "id": DATASET_ID,
            "revision": DATASET_REVISION,
            "component": COMPONENT,
            "test_json": {
                "sha256": sha256_file(test_json),
                "size_bytes": test_json.stat().st_size,
            },
            "labels": {
                "sha256": sha256_file(labels_path),
                "size_bytes": labels_path.stat().st_size,
            },
            "test_archive": {
                "sha256": EXPECTED_TEST_ARCHIVE_SHA256,
                "size_bytes": EXPECTED_TEST_ARCHIVE_BYTES,
                "downloaded": False,
            },
        },
        "adapter": {
            "accepted_schema": "COCO images/annotations/categories",
            "transcription_fields": list(TRANSCRIPTION_FIELDS),
            "category_names_are_not_ocr_truth": True,
            "selection_uses_ocr": False,
            "selection_uses_candidate_output": False,
            "one_numeric_risk_unit_per_image": True,
            "unknown_or_ambiguous_schema": "terminal_no_ocr",
        },
        "schema_census": schema,
        "power_gate": {
            "minimum_selected": MINIMUM_SELECTED,
            "minimum_accepted": MINIMUM_ACCEPTED,
            "development_acceptance_rate": DEVELOPMENT_ACCEPTANCE_RATE,
            "selected_available": selected,
            "selected_pass": selected >= MINIMUM_SELECTED,
            "projected_accepted": projected_accepted,
            "projected_accepted_pass": projected_accepted
            >= MINIMUM_ACCEPTED,
            "download_test_archive_and_run_ocr": run_archive,
        },
        "decision": {
            "schema_census_complete": True,
            "test_archive_opened": False,
            "ocr_executed": False,
            "candidate_inference_executed": False,
            "external_certificate_claimed": False,
            "production_ready": False,
            "automatic_production_change": False,
            "verdict": (
                "CORU_RECEIPT_SCHEMA_AND_POWER_GATE_PASS"
                if run_archive
                else "CORU_RECEIPT_TERMINAL_NO_OCR"
            ),
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    return stable_payload(report, "stable_payload_sha256")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--test-json", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_census(args.test_json, args.labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema_status": report["schema_census"]["schema_status"],
                "counts": report["schema_census"].get("counts", {}),
                "power_gate": report["power_gate"],
                "decision": report["decision"],
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
