"""Outcome-blind source seal for the untouched COCO-Text split.

Only Hugging Face repository metadata is read. No Parquet footer, row, text,
box, polygon, image, OCR output, or benchmark outcome is opened. The seal pins
the immutable repository revision and the exact COCO-Text Parquet object before
numeric-consensus-v7 is bound to this external scene-text corpus.
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
COMPONENT = "cocotext"
API_URL = f"https://huggingface.co/api/datasets/{DATASET_ID}?blobs=true"
MIRROR_DECLARED_LICENSE = "apache-2.0"
UPSTREAM_DECLARED_LICENSE = "cc-by-4.0-annotations; image-terms-upstream"
TARGET_PATTERN = re.compile(r"^data/cocotext(?:-[^/]*)?\.parquet$")
MINIMUM_SOURCE_BYTES = 2_000_000_000
MAXIMUM_SOURCE_BYTES = 3_000_000_000


def fetch_metadata(timeout: float = 60.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OCR-COCOText-V7-Source-Seal/1 outcome-blind",
        },
    )
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(
                request, timeout=timeout
            ) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == 4:
                break
            time.sleep(2 ** attempt)
    raise RuntimeError("COCO-Text metadata fetch failed") from last_error


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
    candidates = (
        lfs.get("sha256"),
        lfs.get("oid"),
        row.get("sha256"),
    )
    for candidate in candidates:
        digest = _normalize_hash(candidate, 64, "sha256:")
        if digest:
            return digest
    raise RuntimeError(f"COCO-Text object lacks SHA-256 identity: {path}")


def seal(metadata: Mapping[str, Any]) -> dict[str, Any]:
    revision = _normalize_hash(metadata.get("sha"), 40)
    if not revision:
        raise RuntimeError("OCR-Data API did not return a full commit SHA")
    siblings = [
        row
        for row in metadata.get("siblings") or []
        if isinstance(row, Mapping)
        and TARGET_PATTERN.fullmatch(str(row.get("rfilename") or ""))
    ]
    if len(siblings) != 1:
        raise RuntimeError(
            "expected exactly one original COCO-Text Parquet object, found "
            f"{[row.get('rfilename') for row in siblings]!r}"
        )
    row = siblings[0]
    path = str(row["rfilename"])
    lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
    size = int(lfs.get("size") or row.get("size") or 0)
    if not MINIMUM_SOURCE_BYTES <= size <= MAXIMUM_SOURCE_BYTES:
        raise RuntimeError(f"COCO-Text source size is implausible: {size}")
    digest = _sha256_identity(row, path)
    if revision != "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c":
        raise RuntimeError(f"unexpected OCR-Data revision: {revision}")
    if path != "data/cocotext-00000-of-00001.parquet":
        raise RuntimeError(f"unexpected COCO-Text source path: {path}")
    if size != 2_223_323_062:
        raise RuntimeError(f"unexpected COCO-Text source size: {size}")
    if digest != "562176cbb803bb7aa140a4537701ef53ebb86e396c8927f9b160227ac49efd48":
        raise RuntimeError("unexpected COCO-Text source SHA-256")
    payload: dict[str, Any] = {
        "schema": "ocr-cocotext-source-seal/7",
        "dataset_id": DATASET_ID,
        "component": COMPONENT,
        "resolved_revision": revision,
        "licenses": {
            "mirror_declared": MIRROR_DECLARED_LICENSE,
            "upstream_cocotext_declared": UPSTREAM_DECLARED_LICENSE,
            "upstream_terms_take_precedence": True,
        },
        "source_object": {
            "path": path,
            "size_bytes": size,
            "sha256": digest,
            "download_url": (
                f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
                f"{revision}/{path}?download=true"
            ),
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
            "reserve one immutable independent COCO-Text scene-text corpus before "
            "binding, census, threshold use, OCR, or candidate inference"
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
        raise RuntimeError("COCO-Text source seal failed stable replay")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
