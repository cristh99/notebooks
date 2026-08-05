"""Outcome-blind source seal for the untouched CORU Receipt component.

Only Hugging Face repository metadata is read. No archive, JSON annotation,
label, image, dataset row, OCR result, or benchmark outcome is downloaded or
opened. The resulting seal pins one immutable repository revision and every
source object needed for a later external receipt validation.
"""
from __future__ import annotations

import argparse
import json
import string
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .core import canonical_json, sha256_bytes

DATASET_ID = "abdoelsayed/CORU"
API_URL = f"https://huggingface.co/api/datasets/{DATASET_ID}?blobs=true"
LICENSE = "mit"
EXPECTED_FILES = (
    "Receipt/labels.txt",
    "Receipt/test.json",
    "Receipt/test.zip",
    "Receipt/train.json",
    "Receipt/train.zip",
    "Receipt/val.json",
    "Receipt/val.zip",
)
ARCHIVE_FILES = (
    "Receipt/test.zip",
    "Receipt/train.zip",
    "Receipt/val.zip",
)
MINIMUM_ARCHIVE_BYTES = 5_000_000_000


def fetch_metadata(timeout: float = 60.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OCR-CORU-Receipt-Source-Seal/1 outcome-blind",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _normalize_hash(value: object, length: int, prefix: str = "") -> str:
    raw = str(value or "").strip().lower()
    if prefix and raw.startswith(prefix):
        raw = raw.removeprefix(prefix)
    if len(raw) != length or any(character not in string.hexdigits for character in raw):
        return ""
    return raw


def _identity(row: Mapping[str, Any], path: str) -> dict[str, str]:
    lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
    sha256 = _normalize_hash(
        lfs.get("sha256") or lfs.get("oid"), 64, "sha256:"
    )
    blob_sha1 = _normalize_hash(row.get("blobId"), 40)
    if sha256:
        return {"algorithm": "sha256", "digest": sha256}
    if blob_sha1:
        return {"algorithm": "git-sha1", "digest": blob_sha1}
    raise RuntimeError(f"CORU source object lacks a cryptographic identity: {path}")


def seal(metadata: Mapping[str, Any]) -> dict[str, Any]:
    revision = _normalize_hash(metadata.get("sha"), 40)
    if not revision:
        raise RuntimeError("CORU API did not return a full commit SHA")
    siblings = {
        str(row.get("rfilename") or ""): row
        for row in metadata.get("siblings") or []
        if isinstance(row, Mapping)
    }
    objects: list[dict[str, Any]] = []
    for path in EXPECTED_FILES:
        row = siblings.get(path)
        if row is None:
            raise RuntimeError(f"CORU repository is missing expected file: {path}")
        lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
        size = int(lfs.get("size") or row.get("size") or 0)
        if size <= 0:
            raise RuntimeError(f"CORU source object lacks a positive size: {path}")
        identity = _identity(row, path)
        if path in ARCHIVE_FILES and identity["algorithm"] != "sha256":
            raise RuntimeError(f"CORU archive lacks a SHA-256 identity: {path}")
        objects.append(
            {
                "path": path,
                "size_bytes": size,
                "identity": identity,
                "download_url": (
                    f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
                    f"{revision}/{path}?download=true"
                ),
            }
        )
    archive_bytes = sum(
        int(row["size_bytes"])
        for row in objects
        if row["path"] in ARCHIVE_FILES
    )
    if archive_bytes < MINIMUM_ARCHIVE_BYTES:
        raise RuntimeError(
            f"CORU Receipt archive bytes unexpectedly small: {archive_bytes}"
        )
    payload: dict[str, Any] = {
        "schema": "ocr-coru-receipt-source-seal/1",
        "dataset_id": DATASET_ID,
        "component": "Receipt",
        "resolved_revision": revision,
        "license": LICENSE,
        "objects": objects,
        "object_count": len(objects),
        "total_source_bytes": sum(int(row["size_bytes"]) for row in objects),
        "total_archive_bytes": archive_bytes,
        "repository_metadata_only": True,
        "archives_downloaded": 0,
        "annotation_bytes_read": 0,
        "labels_read": 0,
        "dataset_rows_read": 0,
        "images_opened": 0,
        "ocr_executed": False,
        "outcomes_opened": False,
        "purpose": (
            "reserve an immutable fresh external receipt corpus before "
            "freezing or evaluating numeric-consensus-v4"
        ),
    }
    payload["stable_payload_sha256"] = sha256_bytes(
        canonical_json(payload).encode("utf-8")
    )
    return payload


def verify(payload: Mapping[str, Any]) -> bool:
    stable = dict(payload)
    observed = str(stable.pop("stable_payload_sha256", ""))
    return observed == sha256_bytes(canonical_json(stable).encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = seal(fetch_metadata())
    if not verify(result):
        raise RuntimeError("CORU source seal failed stable replay")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
