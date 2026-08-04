"""Pure process exclusion and sharding for disjoint OCR validation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Sequence

from .core import Candidate, canonical_json, sha256_bytes
from .final_partition import process_key

SEEN_SCHEMA = "ocr-real-risk-development-seen-processes/1"
SHARD_SCHEMA = "ocr-real-risk-disjoint-development-shard/1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_seen_processes(path: Path) -> tuple[frozenset[str], dict[str, Any]]:
    """Load and validate a sealed list of every previously attempted process."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SEEN_SCHEMA:
        raise ValueError("unsupported seen-process manifest schema")
    keys = [str(value) for value in payload.get("process_keys") or []]
    if not keys or len(keys) != len(set(keys)):
        raise ValueError("seen-process keys must be non-empty and unique")
    if any(not _SHA256_RE.fullmatch(value) for value in keys):
        raise ValueError("seen-process keys must be lowercase SHA-256 values")
    records = payload.get("records") or []
    record_keys = [str(row.get("process_key") or "") for row in records]
    if sorted(record_keys) != sorted(keys):
        raise ValueError("seen-process records do not bind exactly to process_keys")
    canonical_hash = sha256_bytes(
        canonical_json(sorted(keys)).encode("utf-8")
    )
    census = {
        "schema": SEEN_SCHEMA,
        "manifest_path": str(path),
        "manifest_sha256": sha256_bytes(path.read_bytes()),
        "seen_processes": len(keys),
        "process_key_set_sha256": canonical_hash,
        "source_run_id": payload.get("source_run_id"),
        "source_artifact_id": payload.get("source_artifact_id"),
        "source_report_sha256": payload.get("source_report_sha256"),
        "selection_rule": payload.get("selection_rule"),
    }
    return frozenset(keys), census


def validation_shard(process_key_value: str, shard_count: int) -> int:
    """Assign one canonical process to a stable secondary shard."""
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if not _SHA256_RE.fullmatch(process_key_value):
        raise ValueError("process_key_value must be a lowercase SHA-256")
    return int(process_key_value[16:32], 16) % shard_count


def select_disjoint_shard(
    candidates: Sequence[Candidate],
    seen_processes: frozenset[str],
    *,
    shard_index: int,
    shard_count: int,
) -> tuple[list[Candidate], dict[str, Any]]:
    """Exclude all prior processes and select one deterministic validation shard."""
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be in [0, shard_count)")
    keys = [process_key(candidate) for candidate in candidates]
    if len(keys) != len(set(keys)):
        raise ValueError("input candidates must already be process-disjoint")
    remaining = [
        candidate
        for candidate, key in zip(candidates, keys, strict=True)
        if key not in seen_processes
    ]
    selected = [
        candidate
        for candidate in remaining
        if validation_shard(process_key(candidate), shard_count) == shard_index
    ]
    selected.sort(key=lambda candidate: process_key(candidate))
    selected_keys = [process_key(candidate) for candidate in selected]
    if set(selected_keys) & set(seen_processes):
        raise AssertionError("seen process leaked into validation shard")
    return selected, {
        "schema": SHARD_SCHEMA,
        "input_processes": len(candidates),
        "excluded_seen_processes": len(candidates) - len(remaining),
        "remaining_disjoint_processes": len(remaining),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selected_processes": len(selected),
        "selected_process_key_set_sha256": sha256_bytes(
            canonical_json(selected_keys).encode("utf-8")
        ),
        "shard_function": "int(process_key[16:32], 16) mod shard_count",
        "selection_uses_ocr": False,
    }
