"""Outcome-blind source seal for the untouched OpenVINO OCR-Data split.

Only Hugging Face repository metadata is read. No Parquet footer, row, text,
geometry, image, OCR output, or benchmark outcome is opened. The exact object
is pinned before the v7 policy is bound to this corpus.
"""
from __future__ import annotations

import argparse
import json
import re
import string
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .core import canonical_json, sha256_bytes

DATASET_ID = "Yesianrohn/OCR-Data"
COMPONENT = "openvino"
RESOLVED_REVISION = "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c"
SOURCE_PATH = "data/openvino-00000-of-00001.parquet"
SOURCE_SIZE_BYTES = 65_751_927_475
SOURCE_DECLARED_ROWS = 207_790
SOURCE_ADD_COMMIT = "90b74416d90c8f2647d4f5289ecdedc178cc2b97"
SOURCE_SHA256 = "5413c6ffb4f8047977db9dba520453976f48eed91b5477d06e7f62258a2ba09c"
API_URL = f"https://huggingface.co/api/datasets/{DATASET_ID}?blobs=true"
TARGET_PATTERN = re.compile(r"^data/openvino(?:-[^/]*)?\.parquet$")
MINIMUM_SOURCE_BYTES = 60_000_000_000
MAXIMUM_SOURCE_BYTES = 70_000_000_000


def fetch_metadata(timeout: float = 60.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OCR-OpenVINO-V7-Source-Seal/1 outcome-blind",
        },
    )
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == 4:
                break
            time.sleep(2**attempt)
    raise RuntimeError("OpenVINO metadata fetch failed") from last_error


def _normalize_hash(value: object, length: int, prefix: str = "") -> str:
    raw = str(value or "").strip().lower()
    if prefix and raw.startswith(prefix):
        raw = raw.removeprefix(prefix)
    if len(raw) != length or any(
        character not in string.hexdigits for character in raw
    ):
        return ""
    return raw


def _sha256_identity(row: Mapping[str, Any], path: str) -> str:
    lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
    for candidate in (lfs.get("sha256"), lfs.get("oid"), row.get("sha256")):
        digest = _normalize_hash(candidate, 64, "sha256:")
        if digest:
            return digest
    raise RuntimeError(f"OpenVINO object lacks SHA-256 identity: {path}")


def seal(metadata: Mapping[str, Any]) -> dict[str, Any]:
    revision = _normalize_hash(metadata.get("sha"), 40)
    if revision != RESOLVED_REVISION:
        raise RuntimeError(f"unexpected OCR-Data revision: {revision}")
    siblings = [
        row
        for row in metadata.get("siblings") or []
        if isinstance(row, Mapping)
        and TARGET_PATTERN.fullmatch(str(row.get("rfilename") or ""))
    ]
    if len(siblings) != 1:
        raise RuntimeError(
            "expected exactly one original OpenVINO Parquet object, found "
            f"{[row.get('rfilename') for row in siblings]!r}"
        )
    row = siblings[0]
    path = str(row["rfilename"])
    lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
    size = int(lfs.get("size") or row.get("size") or 0)
    digest = _sha256_identity(row, path)
    if not MINIMUM_SOURCE_BYTES <= size <= MAXIMUM_SOURCE_BYTES:
        raise RuntimeError(f"OpenVINO source size is implausible: {size}")
    if path != SOURCE_PATH:
        raise RuntimeError(f"unexpected OpenVINO source path: {path}")
    if size != SOURCE_SIZE_BYTES:
        raise RuntimeError(f"unexpected OpenVINO source size: {size}")
    if digest != SOURCE_SHA256:
        raise RuntimeError("unexpected OpenVINO source SHA-256")

    payload: dict[str, Any] = {
        "schema": "ocr-openvino-source-seal/7",
        "dataset_id": DATASET_ID,
        "component": COMPONENT,
        "resolved_revision": revision,
        "source_object": {
            "path": path,
            "size_bytes": size,
            "sha256": digest,
            "declared_rows": SOURCE_DECLARED_ROWS,
            "declared_rows_source_commit": SOURCE_ADD_COMMIT,
            "download_url": (
                f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
                f"{revision}/{path}?download=true"
            ),
        },
        "license_review": {
            "mirror_declared": "apache-2.0",
            "upstream_terms_independently_resolved": False,
            "full_image_download_requires_review": True,
        },
        "repository_metadata_only": True,
        "parquet_footer_read": False,
        "parquet_bytes_downloaded": 0,
        "dataset_rows_read": 0,
        "texts_opened": 0,
        "bounding_boxes_opened": 0,
        "polygons_opened": 0,
        "images_opened": 0,
        "ocr_executed": False,
        "candidate_inference_executed": False,
        "outcomes_opened": False,
        "purpose": (
            "reserve one immutable independent OpenVINO OCR-Data corpus before "
            "footer access, metadata census, image access, OCR, or inference"
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
        raise RuntimeError("OpenVINO source seal failed stable replay")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
