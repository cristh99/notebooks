"""Seal CORD v2 repository metadata without downloading or opening outcomes.

This module is intentionally incapable of reading parquet rows. It resolves a
single Hugging Face dataset revision, records the exact LFS object identifiers
and sizes of the six source parquet files, and emits a stable hash. External
evaluation must consume this sealed manifest rather than a moving branch.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .core import canonical_json, sha256_bytes

API_URL = "https://huggingface.co/api/datasets/naver-clova-ix/cord-v2"
DATASET_ID = "naver-clova-ix/cord-v2"
EXPECTED_FILES = (
    "data/test-00000-of-00001-9c204eb3f4e11791.parquet",
    "data/train-00000-of-00004-b4aaeceff1d90ecb.parquet",
    "data/train-00001-of-00004-7dbbe248962764c5.parquet",
    "data/train-00002-of-00004-688fe1305a55e5cc.parquet",
    "data/train-00003-of-00004-2d0cd200555ed7fd.parquet",
    "data/validation-00000-of-00001-cc3c5779fe22e8ca.parquet",
)
EXPECTED_ROWS = {"train": 800, "validation": 100, "test": 100}


def fetch_metadata(timeout: float = 60.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OCR-CORD-Source-Seal/1 outcome-blind",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def seal(metadata: Mapping[str, Any]) -> dict[str, Any]:
    revision = str(metadata.get("sha") or "")
    if len(revision) != 40:
        raise RuntimeError("dataset API did not return a full commit SHA")
    siblings = {
        str(row.get("rfilename")): row
        for row in metadata.get("siblings") or []
    }
    files: list[dict[str, Any]] = []
    for path in EXPECTED_FILES:
        row = siblings.get(path)
        if row is None:
            raise RuntimeError(f"missing expected dataset file: {path}")
        lfs = row.get("lfs") or {}
        oid = str(lfs.get("oid") or "")
        size = int(lfs.get("size") or row.get("size") or 0)
        if not oid.startswith("sha256:") or len(oid) != 71:
            raise RuntimeError(f"missing SHA-256 LFS oid for {path}")
        if size <= 0:
            raise RuntimeError(f"missing positive source size for {path}")
        files.append(
            {
                "path": path,
                "size_bytes": size,
                "lfs_oid": oid,
                "download_url": (
                    f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
                    f"{revision}/{path}?download=true"
                ),
            }
        )
    payload: dict[str, Any] = {
        "schema": "ocr-cord-source-seal/1",
        "dataset_id": DATASET_ID,
        "resolved_revision": revision,
        "files": files,
        "expected_rows": EXPECTED_ROWS,
        "expected_total_rows": sum(EXPECTED_ROWS.values()),
        "total_source_bytes": sum(row["size_bytes"] for row in files),
        "outcomes_opened": False,
        "parquet_rows_read": 0,
        "purpose": "freeze external validation source before candidate evaluation",
        "license": "cc-by-4.0",
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = seal(fetch_metadata())
    if not verify(result):
        raise RuntimeError("source seal did not replay")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
