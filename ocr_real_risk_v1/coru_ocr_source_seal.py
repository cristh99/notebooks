"""Outcome-blind source seal for the untouched CORU OCR component.

Only Hugging Face repository metadata is read. No archive member, label,
image, OCR outcome, or benchmark row is downloaded or opened. The seal pins
one immutable repository revision and the exact train/validation/test archives.
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
COMPONENT = "OCR"
API_URL = f"https://huggingface.co/api/datasets/{DATASET_ID}?blobs=true"
LICENSE = "mit"
EXPECTED_FILES = (
    "OCR/test.zip",
    "OCR/train.zip",
    "OCR/val.zip",
)
MINIMUM_TOTAL_BYTES = 250_000_000


def fetch_metadata(timeout: float = 60.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OCR-CORU-OCR-Source-Seal/1 outcome-blind",
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
            raise RuntimeError(f"CORU OCR repository is missing expected file: {path}")
        lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
        digest = _normalize_hash(
            lfs.get("sha256") or lfs.get("oid"), 64, "sha256:"
        )
        size = int(lfs.get("size") or row.get("size") or 0)
        if not digest:
            raise RuntimeError(f"CORU OCR archive lacks SHA-256 identity: {path}")
        if size <= 0:
            raise RuntimeError(f"CORU OCR archive lacks positive size: {path}")
        objects.append(
            {
                "path": path,
                "size_bytes": size,
                "sha256": digest,
                "download_url": (
                    f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
                    f"{revision}/{path}?download=true"
                ),
            }
        )
    total = sum(int(row["size_bytes"]) for row in objects)
    if total < MINIMUM_TOTAL_BYTES:
        raise RuntimeError(f"CORU OCR source bytes unexpectedly small: {total}")
    payload: dict[str, Any] = {
        "schema": "ocr-coru-ocr-source-seal/1",
        "dataset_id": DATASET_ID,
        "component": COMPONENT,
        "resolved_revision": revision,
        "license": LICENSE,
        "objects": objects,
        "object_count": len(objects),
        "total_source_bytes": total,
        "repository_metadata_only": True,
        "archives_downloaded": 0,
        "archive_members_listed": 0,
        "labels_read": 0,
        "images_opened": 0,
        "ocr_executed": False,
        "outcomes_opened": False,
        "purpose": (
            "reserve an immutable line-image OCR corpus before any schema "
            "inspection, threshold change, candidate freeze, or evaluation"
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
        raise RuntimeError("CORU OCR source seal failed stable replay")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
