"""Outcome-blind source seal for an untouched WildReceipt parquet mirror.

Only Hugging Face repository metadata is read. No parquet shard, annotation,
image, dataset row, OCR output, or label is downloaded or opened. The seal pins
one immutable repository revision and every non-empty source object.
"""
from __future__ import annotations

import argparse
import json
import string
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .core import canonical_json, sha256_bytes

DATASET_ID = "kaydee/wildreceipt"
API_URL = f"https://huggingface.co/api/datasets/{DATASET_ID}?blobs=true"
UPSTREAM_DATASET = "WildReceipt"
UPSTREAM_LICENSE = "apache-2.0"
MINIMUM_SOURCE_OBJECTS = 1
MINIMUM_TOTAL_BYTES = 1_000_000_000


def fetch_metadata(timeout: float = 60.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OCR-WildReceipt-Source-Seal/1 outcome-blind",
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


def _source_object(row: Mapping[str, Any], revision: str) -> dict[str, Any] | None:
    path = str(row.get("rfilename") or "").strip()
    if not path or path in {".gitattributes", "README.md"}:
        return None
    lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
    lfs_sha256 = _normalize_hash(
        lfs.get("sha256") or lfs.get("oid"), 64, "sha256:"
    )
    git_blob_sha1 = _normalize_hash(row.get("blobId"), 40)
    size = int(lfs.get("size") or row.get("size") or 0)
    if lfs_sha256:
        identity = {"algorithm": "sha256", "digest": lfs_sha256}
    elif git_blob_sha1:
        identity = {"algorithm": "git-sha1", "digest": git_blob_sha1}
    else:
        raise RuntimeError(f"source object lacks a cryptographic identity: {path}")
    if size <= 0:
        raise RuntimeError(f"source object lacks a positive size: {path}")
    return {
        "path": path,
        "size_bytes": size,
        "identity": identity,
        "download_url": (
            f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
            f"{revision}/{path}?download=true"
        ),
    }


def seal(metadata: Mapping[str, Any]) -> dict[str, Any]:
    revision = str(metadata.get("sha") or "")
    if len(revision) != 40 or any(c not in string.hexdigits for c in revision):
        raise RuntimeError("dataset API did not return a full commit SHA")
    objects = [
        item
        for row in metadata.get("siblings") or []
        if isinstance(row, Mapping)
        if (item := _source_object(row, revision)) is not None
    ]
    objects.sort(key=lambda row: row["path"])
    if len(objects) < MINIMUM_SOURCE_OBJECTS:
        raise RuntimeError("WildReceipt mirror exposes too few sealed objects")
    if len({row["path"] for row in objects}) != len(objects):
        raise RuntimeError("WildReceipt mirror contains duplicate paths")
    total = sum(int(row["size_bytes"]) for row in objects)
    if total < MINIMUM_TOTAL_BYTES:
        raise RuntimeError("WildReceipt mirror source bytes are unexpectedly small")
    card_data = metadata.get("cardData")
    mirror_license = (
        str(card_data.get("license") or "")
        if isinstance(card_data, Mapping)
        else ""
    )
    payload: dict[str, Any] = {
        "schema": "ocr-wildreceipt-source-seal/1",
        "dataset_id": DATASET_ID,
        "resolved_revision": revision,
        "lineage": {
            "upstream_dataset": UPSTREAM_DATASET,
            "upstream_declared_license": UPSTREAM_LICENSE,
            "mirror_declared_license": mirror_license or None,
        },
        "objects": objects,
        "object_count": len(objects),
        "total_source_bytes": total,
        "repository_metadata_only": True,
        "parquet_shards_downloaded": 0,
        "dataset_rows_read": 0,
        "images_opened": 0,
        "annotations_opened": 0,
        "ocr_executed": False,
        "purpose": (
            "reserve an immutable external corpus before digit-forest-v4 "
            "development or threshold selection"
        ),
    }
    payload["stable_payload_sha256"] = sha256_bytes(
        canonical_json(payload).encode("utf-8")
    )
    return payload


def verify(payload: Mapping[str, Any]) -> bool:
    copy = dict(payload)
    observed = str(copy.pop("stable_payload_sha256", ""))
    return observed == sha256_bytes(canonical_json(copy).encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = seal(fetch_metadata())
    if not verify(result):
        raise RuntimeError("WildReceipt source seal did not replay")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
