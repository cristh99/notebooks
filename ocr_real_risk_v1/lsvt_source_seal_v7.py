"""Outcome-blind source seal for the untouched ICDAR-2019 LSVT split.

Only Hugging Face repository metadata is read. No Parquet footer, row,
transcription, geometry, image byte, OCR output, or benchmark outcome is opened.
The upstream non-commercial license is binding; the mirror tag does not replace
upstream terms.
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
COMPONENT = "LSVT"
API_URL = f"https://huggingface.co/api/datasets/{DATASET_ID}?blobs=true"
MIRROR_DECLARED_LICENSE = "apache-2.0"
UPSTREAM_DECLARED_LICENSE = "CC-BY-NC-ND-3.0"
TARGET_PATTERN = re.compile(r"^data/LSVT(?:-[^/]*)?\.parquet$")
EXPECTED_REVISION = "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c"
EXPECTED_PATH = "data/LSVT-00000-of-00001.parquet"
EXPECTED_SIZE = 8_979_134_697
EXPECTED_SHA256 = "44d4e6822060bbd3c11b933675d91ac7da4e944645bee7a080529f0232823c8b"


def fetch_metadata(timeout: float = 60.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OCR-LSVT-V7-Source-Seal/1 outcome-blind",
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
    raise RuntimeError("LSVT metadata fetch failed") from last_error


def _normalize_hash(value: object, length: int, prefix: str = "") -> str:
    raw = str(value or "").strip().lower()
    if prefix and raw.startswith(prefix):
        raw = raw.removeprefix(prefix)
    if len(raw) != length or any(character not in string.hexdigits for character in raw):
        return ""
    return raw


def _sha256_identity(row: Mapping[str, Any], path: str) -> str:
    lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
    for candidate in (lfs.get("sha256"), lfs.get("oid"), row.get("sha256")):
        digest = _normalize_hash(candidate, 64, "sha256:")
        if digest:
            return digest
    raise RuntimeError(f"LSVT object lacks SHA-256 identity: {path}")


def seal(metadata: Mapping[str, Any]) -> dict[str, Any]:
    revision = _normalize_hash(metadata.get("sha"), 40)
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f"unexpected OCR-Data revision: {revision}")
    siblings = [
        row
        for row in metadata.get("siblings") or []
        if isinstance(row, Mapping)
        and TARGET_PATTERN.fullmatch(str(row.get("rfilename") or ""))
    ]
    if len(siblings) != 1:
        raise RuntimeError(
            "expected exactly one LSVT Parquet object, found "
            f"{[row.get('rfilename') for row in siblings]!r}"
        )
    row = siblings[0]
    path = str(row["rfilename"])
    lfs = row.get("lfs") if isinstance(row.get("lfs"), Mapping) else {}
    size = int(lfs.get("size") or row.get("size") or 0)
    digest = _sha256_identity(row, path)
    if path != EXPECTED_PATH or size != EXPECTED_SIZE or digest != EXPECTED_SHA256:
        raise RuntimeError("unexpected LSVT source identity")
    payload: dict[str, Any] = {
        "schema": "ocr-lsvt-source-seal/7",
        "dataset_id": DATASET_ID,
        "component": COMPONENT,
        "resolved_revision": revision,
        "licenses": {
            "mirror_declared": MIRROR_DECLARED_LICENSE,
            "upstream_lsvt_declared": UPSTREAM_DECLARED_LICENSE,
            "upstream_terms_take_precedence": True,
            "commercial_use_forbidden": True,
            "source_images_must_not_be_redistributed": True,
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
            "reserve one immutable independent LSVT corpus before binding, "
            "census, OCR, candidate inference, or outcomes"
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
        raise RuntimeError("LSVT source seal stable replay failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
