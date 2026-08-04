"""Fail-closed structural validation of a sealed OCR holdout manifest."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .core import verify_manifest_hash


def validate(manifest: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    documents = list(manifest.get("documents") or [])
    crops = list(manifest.get("crops") or [])
    summary = manifest.get("summary") or {}

    if not verify_manifest_hash(manifest):
        errors.append("manifest hash mismatch")
    if not summary.get("complete"):
        errors.append("manifest preparation is incomplete")
    if len(documents) != len(crops):
        errors.append("document and crop denominators differ")

    unit_ids = [str(row.get("unit_id") or "") for row in crops]
    source_hashes = [str(row.get("source_sha256") or "") for row in documents]
    crop_ids = [str(row.get("crop_id") or "") for row in crops]
    document_indices = [int(row.get("document_index", -1)) for row in crops]

    duplicate_units = sorted(
        key for key, count in Counter(unit_ids).items() if key and count > 1
    )
    duplicate_sources = sorted(
        key for key, count in Counter(source_hashes).items() if key and count > 1
    )
    duplicate_crops = sorted(
        key for key, count in Counter(crop_ids).items() if key and count > 1
    )
    duplicate_document_indices = sorted(
        key
        for key, count in Counter(document_indices).items()
        if key >= 0 and count > 1
    )

    if not all(unit_ids):
        errors.append("one or more crop units are empty")
    if not all(source_hashes):
        errors.append("one or more source hashes are empty")
    if not all(crop_ids):
        errors.append("one or more crop identities are empty")
    if duplicate_units:
        errors.append("duplicate procurement units")
    if duplicate_sources:
        errors.append("duplicate source PDF hashes")
    if duplicate_crops:
        errors.append("duplicate crop identities")
    if duplicate_document_indices:
        errors.append("more than one crop points to a document")

    expected_indices = set(range(len(documents)))
    if set(document_indices) != expected_indices:
        errors.append("crop document indices are not an exact permutation")

    for crop in crops:
        index = int(crop.get("document_index", -1))
        if index < 0 or index >= len(documents):
            continue
        document = documents[index]
        if crop.get("unit_id") != document.get("unit_id"):
            errors.append(f"unit binding mismatch at document {index}")
        if crop.get("source_sha256") != document.get("source_sha256"):
            errors.append(f"source hash binding mismatch at document {index}")
        if crop.get("ocid") != document.get("ocid"):
            errors.append(f"OCID binding mismatch at document {index}")

    declared_unique_ocids = int(summary.get("unique_ocids") or 0)
    if declared_unique_ocids != len(set(unit_ids)):
        errors.append("declared unique-OCID denominator does not replay")

    return {
        "valid": not errors,
        "errors": errors,
        "documents": len(documents),
        "crops": len(crops),
        "unique_units": len(set(unit_ids)),
        "unique_source_sha256": len(set(source_hashes)),
        "unique_crop_ids": len(set(crop_ids)),
        "duplicate_units": duplicate_units,
        "duplicate_source_sha256": duplicate_sources,
        "duplicate_crop_ids": duplicate_crops,
        "duplicate_document_indices": duplicate_document_indices,
        "manifest_sha256": manifest.get("manifest_sha256"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    result = validate(json.loads(args.manifest.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
