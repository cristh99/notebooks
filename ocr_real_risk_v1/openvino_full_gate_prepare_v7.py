"""Authorized OpenVINO v7 physical-registry and partition executors.

No source access occurs at import time.  Every image-reading entry point requires
a hash-bound one-shot authorization.  A partition's detector barrier is persisted
before annotation text or geometry is queried.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import sha256_bytes
from .openvino_full_gate_contract_v7 import (
    SOURCE_URL,
    _read_jsonl,
    canonical_pixel_sha256,
    stable_payload,
    verify_execution_authorization,
    verify_manifest_bundle,
)
from .openvino_full_gate_registry_v7 import (
    _image_id_from_path,
    _load_prior_registry,
    build_physical_registry,
    write_registry_bundle,
)


def _duckdb_connection() -> Any:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - runtime-only path
        raise RuntimeError("duckdb==1.5.5 is required for full-gate execution") from exc
    connection = duckdb.connect(database=":memory:")
    connection.execute("SET threads=1")
    connection.execute("SET preserve_insertion_order=true")
    return connection


def _quote_sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _insert_manifest_table(connection: Any, rows: Sequence[Mapping[str, Any]]) -> None:
    connection.execute(
        "CREATE TEMP TABLE requested_rows("
        "row_index BIGINT PRIMARY KEY, image_id VARCHAR, partition INTEGER, "
        "selection_rank_sha256 VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO requested_rows VALUES (?, ?, ?, ?)",
        [
            (
                int(row["row_index"]),
                str(row["image_id"]),
                int(row["partition"]),
                str(row["selection_rank_sha256"]),
            )
            for row in rows
        ],
    )


def _image_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, Mapping):
        raw = value.get("bytes")
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, bytearray):
            return bytes(raw)
    raise RuntimeError("OpenVINO image bytes have an unsupported representation")


def prepare_registry_from_source(
    *,
    manifest_root: Path,
    prior_registry_path: Path,
    prior_registry_sha256: str,
    authorization_path: Path,
    authorization_sha256: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Open image bytes only; never read annotation columns or run OCR."""
    authorization = verify_execution_authorization(
        authorization_path, authorization_sha256, "PREPARE_REGISTRY"
    )
    verify_manifest_bundle(manifest_root)
    prior = _load_prior_registry(prior_registry_path, prior_registry_sha256)
    scientific = _read_jsonl(Path(manifest_root) / "scientific_manifest.jsonl")
    connection = _duckdb_connection()
    _insert_manifest_table(connection, scientific)
    source = _quote_sql(SOURCE_URL)
    cursor = connection.execute(
        "SELECT r.row_index, r.image_id, r.partition, r.selection_rank_sha256, "
        "p.image.path::VARCHAR, p.image.bytes "
        f"FROM read_parquet({source}, file_row_number=true) p "
        "JOIN requested_rows r ON r.row_index = p.file_row_number "
        "ORDER BY r.row_index"
    )
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - runtime-only path
        raise RuntimeError("Pillow==12.2.0 is required") from exc
    image_records: list[dict[str, Any]] = []
    while True:
        batch = cursor.fetchmany(8)
        if not batch:
            break
        for row_index, image_id, partition, rank, path, raw_value in batch:
            if _image_id_from_path(path) != image_id:
                raise RuntimeError("OpenVINO path/ImageID binding drift")
            raw = _image_bytes(raw_value)
            if not raw:
                raise RuntimeError("OpenVINO source returned empty image bytes")
            try:
                with Image.open(io.BytesIO(raw)) as opened:
                    image = opened.convert("RGB")
            except Exception as exc:
                raise RuntimeError(f"OpenVINO image decode failed: {row_index}") from exc
            image_records.append(
                {
                    "row_index": int(row_index),
                    "image_id": str(image_id),
                    "partition": int(partition),
                    "selection_rank_sha256": str(rank),
                    "encoded_sha256": sha256_bytes(raw),
                    "pixel_sha256": canonical_pixel_sha256(image),
                    "encoded_bytes": len(raw),
                    "width": image.width,
                    "height": image.height,
                    "mode": "RGB",
                }
            )
            del raw
        print(
            json.dumps(
                {
                    "phase": "physical_registry",
                    "rows": len(image_records),
                    "expected": len(scientific),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    registry = build_physical_registry(scientific, image_records, prior)
    registry = stable_payload(
        {
            **{
                key: value
                for key, value in registry.items()
                if key != "stable_payload_sha256"
            },
            "authorization_binding": {
                "execution_id": authorization["execution_id"],
                "authorization_nonce_sha256": authorization[
                    "authorization_nonce_sha256"
                ],
                "authorization_stable_payload_sha256": authorization[
                    "stable_payload_sha256"
                ],
                "authorization_file_sha256": authorization_sha256,
            },
        }
    )
    write_registry_bundle(registry, output_dir)
    return registry
