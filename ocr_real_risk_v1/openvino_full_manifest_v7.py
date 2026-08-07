"""Metadata-only manifest preflight for the preregistered OpenVINO v7 full gate.

This program never selects ``image.bytes``. It recomputes the exact frozen
numeric selection from annotations, binds each selected row to ``image.path`` /
ImageID, removes the fixed 16-row engineering smoke, and materializes the 12
scientific partitions. It cannot run OCR, candidate inference, aggregation, or
scientific quality tests.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import duckdb

from ocr_real_risk_v1.core import canonical_json, sha256_bytes
from ocr_real_risk_v1.textocr_adapter_v6 import select_numeric_annotation

SCHEMA = "eaat.openvino_v7_full_manifest_preflight/v1"
SOURCE_COMMIT = "fa20f6d210fa8be7272178b1f152e38b2d583637"
SOURCE_URL = (
    "https://huggingface.co/datasets/Yesianrohn/OCR-Data/resolve/"
    "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c/"
    "data/openvino-00000-of-00001.parquet?download=true"
)
SOURCE_OBJECT_SHA256 = (
    "5413c6ffb4f8047977db9dba520453976f48eed91b5477d06e7f62258a2ba09c"
)
EXPECTED_SOURCE_ROWS = 207_790
EXPECTED_SELECTED = 20_629
EXPECTED_SELECTED_RECORD_SET_SHA256 = (
    "35ad9e1e43d81ef826f10a04659f77cacf13b987360e83625b52edcd7e223870"
)
EXPECTED_SCIENTIFIC = 20_613
EXPECTED_PARTITION_COUNTS = [
    1684,
    1729,
    1696,
    1684,
    1658,
    1715,
    1728,
    1749,
    1761,
    1751,
    1762,
    1696,
]
EXPECTED_MACROFOLD_COUNTS = [5109, 5057, 5238, 5209]
SMOKE_DOMAIN = b"OPENVINO-V7-SMOKE-EXCLUDE-V1\x1f"
PARTITION_DOMAIN = b"OPENVINO-V7-PARTITION-V1\x1f"
EXPECTED_SMOKE = [
    (1, 80108, "298cadbae09ccedb", "000132ee866c618192aa0ea43e4ba93f83cb8ae14684e66b6415cdfea67deaba"),
    (2, 97623, "2f59c53adbcbebaf", "00015978692a8d0743b31196e348e70fca3dc25494b245d042aa94c04ef7791c"),
    (3, 132271, "5a92951f558f9576", "0001de0a42f785bbf6b6712898cf6868d65efa380c9a179fd030110464a4d918"),
    (4, 89731, "2cb6b047b0a43daf", "0002ba132fa06e65430b182e2a89b50ff28273899b2bedd3c0748bff164012bb"),
    (5, 12504, "1c00e32279ef8678", "0005e1f924da62e57ba14340fe1705f37fb2d912df7d7ac4bf752687827c1a96"),
    (6, 127767, "59211f4813bc7ac7", "000627692935d9e4713143f4ce81f92b7c286a3694338a90d45eb0a4d83f5fc9"),
    (7, 191703, "099a638d78046e76", "0009fb7c9f184b3cbcde2ee88e90549613ae20b393273756c4acca9fefdd0cbc"),
    (8, 44625, "11e237f57418b2b2", "000a1f9bf006e9a5494e6ef7bbf87a3f218ec8f1c6953f4192fe6c8e2737d501"),
    (9, 91944, "2d730228a11fda4c", "000c38f78135e7acfac9a32914d812952ce604c8c8c10aa8753b5a7ed552d0d9"),
    (10, 193955, "2afaedc20f715c25", "0011e9d3131900a1af7e466a4ee79fc44f0077ef00be11d4015fc73b14f2ad1c"),
    (11, 74899, "27d31d0e3444b239", "001270d58998d17f7f53f91f83ae98ab21c3a2afa8398c3f1057f340f4472678"),
    (12, 207373, "fa3d890c4d8eab8e", "0012f695cd5d198b4f29444072862a72131a44a89dea0b7aa765ced01b6cae85"),
    (13, 75546, "280838e7e4d6d776", "001377a56ccc2f2521792b706c7bc226d100547ed69303f25ae2525f6ccf9c01"),
    (14, 52897, "20c1c8cccb1b3cfe", "0013930bb6a57a268a2094a91c689a69729316da1732e354eb9ef28a63e2c1f9"),
    (15, 103733, "5148ba9f4eda9f13", "0013f1d3719d853f8bff2259160d47f947fd049dfbb8f07677de26540b9b2e0e"),
    (16, 135780, "5bbe4e23749c4f40", "0016b97cbc1577fc6c77a25c7037aa64650891a926ae4badf7969ddd0ac3e3de"),
]
FROZEN_FILES = (
    "ocr_real_risk_v1/core.py",
    "ocr_real_risk_v1/textocr_adapter_v6.py",
)


def _quote_sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def verify_source_identity() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in FROZEN_FILES:
        path = Path(relative)
        current_blob = _git("hash-object", relative)
        frozen_blob = _git("rev-parse", f"{SOURCE_COMMIT}:{relative}")
        if current_blob != frozen_blob:
            raise RuntimeError(f"frozen source drift: {relative}")
        records.append(
            {
                "path": relative,
                "git_blob_sha1": current_blob,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def image_id_from_path(value: object) -> str:
    path = str(value or "")
    leaf = path.rsplit("/", 1)[-1]
    image_id = leaf.rsplit(".", 1)[0].lower()
    if len(image_id) != 16 or any(ch not in "0123456789abcdef" for ch in image_id):
        raise RuntimeError(f"invalid Open Images ImageID path: {path}")
    return image_id


def smoke_rank(image_id: str) -> str:
    return hashlib.sha256(SMOKE_DOMAIN + image_id.encode("ascii")).hexdigest()


def partition_index(image_id: str) -> int:
    digest = hashlib.sha256(PARTITION_DOMAIN + image_id.encode("ascii")).hexdigest()
    return int(digest[:16], 16) % 12


def canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> str:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    started = time.perf_counter()
    source_files = verify_source_identity()
    connection = duckdb.connect(database=":memory:")
    connection.execute("SET threads=1")
    connection.execute("SET preserve_insertion_order=true")
    source = _quote_sql(SOURCE_URL)
    description = connection.execute(
        f"DESCRIBE SELECT image.path, texts, bboxes, polygons, num_text_regions "
        f"FROM read_parquet({source})"
    ).fetchall()
    names = [str(row[0]) for row in description]
    if "bytes" in names:
        raise RuntimeError("image.bytes unexpectedly entered projected schema")
    cursor = connection.execute(
        "SELECT file_row_number::BIGINT AS row_index, image.path::VARCHAR AS image_path, "
        "texts, bboxes, polygons, num_text_regions "
        f"FROM read_parquet({source}, file_row_number=true) "
        "ORDER BY file_row_number"
    )
    selected_records: list[dict[str, Any]] = []
    identity_rows: list[dict[str, Any]] = []
    row_count = 0
    while True:
        batch = cursor.fetchmany(128)
        if not batch:
            break
        for raw_index, raw_path, texts, bboxes, polygons, num_regions in batch:
            row_index = int(raw_index)
            row_count += 1
            selected, _counts = select_numeric_annotation(
                row_index=row_index,
                texts=texts,
                bboxes=bboxes,
                polygons=polygons,
                num_text_regions=num_regions,
            )
            if selected is None:
                continue
            image_id = image_id_from_path(raw_path)
            selected_records.append(selected)
            identity_rows.append(
                {
                    "row_index": row_index,
                    "image_id": image_id,
                    "selection_rank_sha256": str(selected["selection_rank_sha256"]),
                }
            )
        if row_count % 8192 == 0:
            print(
                json.dumps(
                    {
                        "phase": "metadata_manifest_scan",
                        "rows_scanned": row_count,
                        "selected": len(selected_records),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    if row_count != EXPECTED_SOURCE_ROWS:
        raise RuntimeError(f"source row drift: {row_count}")
    selected_records.sort(key=lambda row: int(row["row_index"]))
    identity_rows.sort(key=lambda row: int(row["row_index"]))
    selected_sha = canonical_sha(selected_records)
    if len(selected_records) != EXPECTED_SELECTED:
        raise RuntimeError(f"selected count drift: {len(selected_records)}")
    if selected_sha != EXPECTED_SELECTED_RECORD_SET_SHA256:
        raise RuntimeError(f"selected record-set drift: {selected_sha}")
    image_ids = [str(row["image_id"]) for row in identity_rows]
    if len(set(image_ids)) != EXPECTED_SELECTED:
        raise RuntimeError("ImageID uniqueness drift")

    ranked = sorted(
        (
            smoke_rank(str(row["image_id"])),
            int(row["row_index"]),
            str(row["image_id"]),
        )
        for row in identity_rows
    )
    observed_smoke = [
        (rank, row_index, image_id, rank_sha)
        for rank, (rank_sha, row_index, image_id) in enumerate(ranked[:16], start=1)
    ]
    if observed_smoke != EXPECTED_SMOKE:
        raise RuntimeError("frozen smoke exclusion drift")
    smoke_ids = {image_id for _rank, _row, image_id, _sha in EXPECTED_SMOKE}

    scientific: list[dict[str, Any]] = []
    partitions: dict[int, list[dict[str, Any]]] = {index: [] for index in range(12)}
    for row in identity_rows:
        if row["image_id"] in smoke_ids:
            continue
        partition = partition_index(str(row["image_id"]))
        manifest_row = {
            "row_index": int(row["row_index"]),
            "image_id": str(row["image_id"]),
            "partition": partition,
            "selection_rank_sha256": str(row["selection_rank_sha256"]),
        }
        scientific.append(manifest_row)
        partitions[partition].append(manifest_row)
    if len(scientific) != EXPECTED_SCIENTIFIC:
        raise RuntimeError(f"scientific denominator drift: {len(scientific)}")
    partition_counts = [len(partitions[index]) for index in range(12)]
    if partition_counts != EXPECTED_PARTITION_COUNTS:
        raise RuntimeError(f"partition count drift: {partition_counts}")
    macrofold_counts = [
        sum(partition_counts[start : start + 3]) for start in (0, 3, 6, 9)
    ]
    if macrofold_counts != EXPECTED_MACROFOLD_COUNTS:
        raise RuntimeError(f"macrofold count drift: {macrofold_counts}")

    output = Path("openvino-full-manifest-output")
    output.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    files["selected_identity.jsonl"] = write_jsonl(
        output / "selected_identity.jsonl", identity_rows
    )
    files["scientific_manifest.jsonl"] = write_jsonl(
        output / "scientific_manifest.jsonl", scientific
    )
    for index in range(12):
        name = f"partition_{index:02d}.jsonl"
        files[name] = write_jsonl(output / name, partitions[index])
    smoke_rows = [
        {
            "rank": rank,
            "row_index": row_index,
            "image_id": image_id,
            "rank_sha256": rank_sha,
        }
        for rank, row_index, image_id, rank_sha in EXPECTED_SMOKE
    ]
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_METADATA_ONLY_FULL_MANIFEST",
        "source": {
            "revision": "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c",
            "object_sha256": SOURCE_OBJECT_SHA256,
            "source_rows": row_count,
            "projected_columns": [
                "image.path",
                "texts",
                "bboxes",
                "polygons",
                "num_text_regions",
            ],
            "image_bytes_read": False,
        },
        "frozen_source_files": source_files,
        "selected": {
            "count": len(identity_rows),
            "selected_record_set_sha256": selected_sha,
            "unique_image_ids": len(set(image_ids)),
            "identity_manifest_sha256": files["selected_identity.jsonl"],
        },
        "engineering_exclusion": {
            "count": 16,
            "domain": "OPENVINO-V7-SMOKE-EXCLUDE-V1",
            "rows": smoke_rows,
        },
        "scientific": {
            "count": len(scientific),
            "partition_rule": (
                "uint64(first 16 hex SHA256(OPENVINO-V7-PARTITION-V1 || 0x1f || ImageID)) mod 12"
            ),
            "partition_counts": partition_counts,
            "macrofold_counts": macrofold_counts,
            "manifest_sha256": files["scientific_manifest.jsonl"],
            "partition_file_sha256": {
                f"{index:02d}": files[f"partition_{index:02d}.jsonl"]
                for index in range(12)
            },
        },
        "files": files,
        "execution": {
            "wall_seconds": time.perf_counter() - started,
            "images_opened": 0,
            "ocr_runs": 0,
            "candidate_inference_runs": 0,
            "external_spend_usd": 0,
            "production_modified": False,
        },
        "full_gate_authorized": False,
        "next_gate": "FREEZE_AND_REVIEW_12_SHARD_RUNNER_AND_AGGREGATOR",
    }
    receipt["receipt_sha256"] = canonical_sha(receipt)
    receipt_path = output / "manifest_receipt.json"
    write_json(receipt_path, receipt)
    files["manifest_receipt.json"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    sums = output / "SHA256SUMS.txt"
    sums.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(files.items())),
        encoding="utf-8",
    )
    print("@@OPENVINO_FULL_MANIFEST@@" + json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
