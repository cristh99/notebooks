"""Frozen identities, authorization, manifest, and physical-dedup contracts.

This module is side-effect free except for explicit artifact read/write helpers.
It cannot query the OpenVINO source, run OCR, or execute candidate inference.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .core import canonical_json, sha256_bytes, sha256_file

# Frozen identity and protocol bindings.
SOURCE_COMMIT = "fa20f6d210fa8be7272178b1f152e38b2d583637"
SOURCE_REVISION = "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c"
SOURCE_URL = (
    "https://huggingface.co/datasets/Yesianrohn/OCR-Data/resolve/"
    f"{SOURCE_REVISION}/data/openvino-00000-of-00001.parquet?download=true"
)
SOURCE_OBJECT_SHA256 = (
    "5413c6ffb4f8047977db9dba520453976f48eed91b5477d06e7f62258a2ba09c"
)
SOURCE_SIZE_BYTES = 65_751_927_475
SOURCE_ROWS = 207_790
CANDIDATE_STABLE_PAYLOAD_SHA256 = (
    "160a3e79c6075a6741a1a6365b0c833115bfc6e156176cb4cb5744b1189119cd"
)
MODEL_ARTIFACT_ID = 8917522937
MODEL_ZIP_SHA256 = (
    "080b0efd4b91a180a1a5c6acd767d72e0a8f286718e64eb90d8ec9d370d2dc17"
)
MODEL_SHA256 = (
    "53229915331c2bbea2454f9e7cb5768a26e9edb30de750747f4397f1ff4cf92c"
)
MODEL_CANDIDATE_STABLE_SHA256 = (
    "0f88d94af81e0f7921e654e452059d2075b07ee35bcffd83dd8b02ebdd9e93a1"
)
POLICY_SOURCE_SHA256 = (
    "5b37aa3ac9f349e708624e815dab97e2ab1eaaac4a905499de15aa3513862b2d"
)
MANIFEST_RECEIPT_FILE_SHA256 = (
    "1ece1fcf947b9df31f6833cf7251f74fd02fb993c097fa6a4b09d64eb348205b"
)
MANIFEST_RECEIPT_SELF_SHA256 = (
    "7338502c00873c0c977e607e8c25f54c5f55da5fdf93b21c99d485c684d9a9fa"
)
SELECTED_IDENTITY_SHA256 = (
    "82c0aa4e78b92881f1158ba98f5869d1b4df26b6f91f3e9ee4002fb35e5f727b"
)
SCIENTIFIC_MANIFEST_SHA256 = (
    "3340183dca08229e3cd1d17472043316867381d8b4f70e6f2d74e3592cd89d4c"
)
SELECTED_RECORD_SET_SHA256 = (
    "35ad9e1e43d81ef826f10a04659f77cacf13b987360e83625b52edcd7e223870"
)
EXPECTED_SELECTED = 20_629
EXPECTED_SCIENTIFIC = 20_613
PARTITION_COUNT = 12
MACROFOLD_COUNT = 4
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
EXPECTED_MANIFEST_FILES = {
    "partition_00.jsonl": "ed5076f77d3a7223dd925220ed3b16e024ee6acda2031e4443d275292523e15a",
    "partition_01.jsonl": "6d386853444569454f0131c02b1274d2827cd03651eca57ead52ade0f2f95bea",
    "partition_02.jsonl": "e75e1e1d2c03bf8bd43e7d90a6a67cbc2a58192d0cbfaaf3f35e357d768be759",
    "partition_03.jsonl": "caf750f307e516c543e27c88e82abbceab44ea1ebc2ae23f7de875d7febc0230",
    "partition_04.jsonl": "a4a9b27b9e0fb5d0d977e725f85075cde81c1990c8c3c2892c5b7ae76e0db3ce",
    "partition_05.jsonl": "2c54b40d643b3e129cfa93555b60018ddb5e40ec46b9f86c21efece697cf8a9d",
    "partition_06.jsonl": "c1f73e5b3322a3a688138ad496a82dd8f70991a8918d765568d5f53507c41953",
    "partition_07.jsonl": "55dba4589aa6197140e28352014c14af063ebab60f8c9ff53dc7fadb582eda79",
    "partition_08.jsonl": "9f533f7eb05b9c8a3f33fd013a26f4080d8a768a87fbb1345d02f33068bc5222",
    "partition_09.jsonl": "1829fc8d03c4d513f7cafbf05802dd0c80e43f2171c1761a8d51b27a51d33acd",
    "partition_10.jsonl": "5987dd770f459b8eb9a55b8b663bca4547ddc9516240f33413031bf61ad4f03b",
    "partition_11.jsonl": "1c356dab4d696e844867f5e58865a3858754897ee9c5e38ecd5bc950214e32e3",
    "scientific_manifest.jsonl": SCIENTIFIC_MANIFEST_SHA256,
    "selected_identity.jsonl": SELECTED_IDENTITY_SHA256,
}
RETIRED_CORPORA = ("SROIE", "CORD", "WildReceipt", "TextOCR", "COCO-Text")

# Frozen statistical contract.
FAMILY_ALPHA = 0.05
ALPHA_PER_LEG = FAMILY_ALPHA / 4.0
TARGET_ERROR_REDUCTION = 10.0
MINIMUM_COVERAGE_LOWER = 0.25
COUNTERFACTUAL_MAXIMUM_UPPER = 0.01
MINIMUM_MACROFOLD_PASS_FRACTION = 0.75
DEVELOPMENT_ACCEPTANCE_NUMERATOR = 110
DEVELOPMENT_ACCEPTANCE_DENOMINATOR = 4674
MINIMUM_PROJECTED_VERIFIED = 400
MINIMUM_ACTIVE_AFTER_DEDUP = math.ceil(
    MINIMUM_PROJECTED_VERIFIED
    * DEVELOPMENT_ACCEPTANCE_DENOMINATOR
    / DEVELOPMENT_ACCEPTANCE_NUMERATOR
)

# Schemas and terminal semantics.
AUTHORIZATION_SCHEMA = "eaat.openvino_v7_full_execution_authorization/1"
PRIOR_REGISTRY_SCHEMA = "eaat.openvino_v7_prior_corpus_fingerprint_registry/1"
REGISTRY_SCHEMA = "eaat.openvino_v7_physical_dedup_registry/1"
PARTITION_REPORT_SCHEMA = "eaat.openvino_v7_partition_report/1"
AGGREGATE_SCHEMA = "eaat.openvino_v7_external_aggregate/1"
PASS_FULL_EXTERNAL_GATE = "PASS_FULL_EXTERNAL_GATE"
FAIL_FULL_EXTERNAL_GATE = "FAIL_FULL_EXTERNAL_GATE"
ABSTAIN_DEDUP_OR_INTEGRITY = "ABSTAIN_DEDUP_OR_INTEGRITY"
BLOCKED_ENGINEERING = "BLOCKED_ENGINEERING"
REGISTRY_READY = "REGISTRY_READY_NO_OCR"
ACTIVE = "ACTIVE"
EXCLUDED_INTERNAL_DUPLICATE = "EXCLUDED_INTERNAL_DUPLICATE"
EXCLUDED_PRIOR_OVERLAP = "EXCLUDED_PRIOR_OVERLAP"

_HEX = frozenset("0123456789abcdef")


def stable_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical payload with a self-authenticating SHA-256 field."""
    result = dict(payload)
    result.pop("stable_payload_sha256", None)
    result["stable_payload_sha256"] = sha256_bytes(
        canonical_json(result).encode("utf-8")
    )
    return result


def verify_stable_payload(payload: Mapping[str, Any]) -> bool:
    expected = str(payload.get("stable_payload_sha256") or "")
    return len(expected) == 64 and stable_payload(payload)[
        "stable_payload_sha256"
    ] == expected


def _is_sha256(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(character in _HEX for character in text)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                raise RuntimeError(f"blank JSONL row: {path}:{line_number}")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise RuntimeError(f"JSONL object required: {path}:{line_number}")
            result.append(value)
    return result


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def write_hash_manifest(root: Path) -> None:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (root / "SHA256SUMS.txt").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
    )


def verify_hash_manifest(root: Path, *, exact_files: set[str] | None = None) -> None:
    manifest = root / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise RuntimeError(f"missing SHA256SUMS.txt: {root}")
    observed: set[str] = set()
    for line_number, raw in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if "  " not in raw:
            raise RuntimeError(f"invalid SHA256SUMS line {line_number}")
        expected, relative = raw.split("  ", 1)
        if relative in observed or not _is_sha256(expected):
            raise RuntimeError(f"invalid or duplicate SHA256SUMS entry: {relative}")
        target = root / relative
        if not target.is_file() or sha256_file(target) != expected:
            raise RuntimeError(f"SHA-256 mismatch: {relative}")
        observed.add(relative)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    if observed != actual:
        raise RuntimeError("SHA256SUMS does not cover exactly the artifact files")
    if exact_files is not None and actual != exact_files:
        raise RuntimeError(f"artifact file-set drift: {sorted(actual ^ exact_files)}")


def verify_manifest_bundle(root: Path) -> dict[str, Any]:
    """Replay the exact terminal metadata-only manifest artifact."""
    root = Path(root)
    required = {"manifest_receipt.json", *EXPECTED_MANIFEST_FILES}
    verify_hash_manifest(root, exact_files=required)
    receipt_path = root / "manifest_receipt.json"
    if sha256_file(receipt_path) != MANIFEST_RECEIPT_FILE_SHA256:
        raise RuntimeError("manifest receipt file SHA-256 drift")
    receipt = _read_json(receipt_path)
    expected_self = str(receipt.get("receipt_sha256") or "")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    observed_self = sha256_bytes(canonical_json(unsigned).encode("utf-8"))
    if expected_self != MANIFEST_RECEIPT_SELF_SHA256 or observed_self != expected_self:
        raise RuntimeError("manifest receipt self-hash replay failed")
    if (
        receipt.get("schema") != "eaat.openvino_v7_full_manifest_preflight/v1"
        or receipt.get("status") != "PASS_METADATA_ONLY_FULL_MANIFEST"
        or receipt.get("full_gate_authorized") is not False
        or receipt.get("source", {}).get("object_sha256") != SOURCE_OBJECT_SHA256
        or int(receipt.get("source", {}).get("source_rows") or -1) != SOURCE_ROWS
        or receipt.get("source", {}).get("image_bytes_read") is not False
        or receipt.get("selected", {}).get("count") != EXPECTED_SELECTED
        or receipt.get("selected", {}).get("selected_record_set_sha256")
        != SELECTED_RECORD_SET_SHA256
        or receipt.get("scientific", {}).get("count") != EXPECTED_SCIENTIFIC
        or receipt.get("scientific", {}).get("manifest_sha256")
        != SCIENTIFIC_MANIFEST_SHA256
        or receipt.get("scientific", {}).get("partition_counts")
        != EXPECTED_PARTITION_COUNTS
        or receipt.get("scientific", {}).get("macrofold_counts")
        != EXPECTED_MACROFOLD_COUNTS
    ):
        raise RuntimeError("terminal manifest receipt contract drift")
    for name, expected in EXPECTED_MANIFEST_FILES.items():
        if receipt.get("files", {}).get(name) != expected:
            raise RuntimeError(f"receipt file binding drift: {name}")
        if sha256_file(root / name) != expected:
            raise RuntimeError(f"manifest file SHA-256 drift: {name}")

    selected = _read_jsonl(root / "selected_identity.jsonl")
    scientific = _read_jsonl(root / "scientific_manifest.jsonl")
    if len(selected) != EXPECTED_SELECTED or len(scientific) != EXPECTED_SCIENTIFIC:
        raise RuntimeError("terminal manifest denominator drift")
    selected_rows: set[int] = set()
    selected_ids: set[str] = set()
    for row in selected:
        row_index = int(row.get("row_index", -1))
        image_id = str(row.get("image_id") or "")
        rank = str(row.get("selection_rank_sha256") or "")
        if (
            row_index < 0
            or row_index in selected_rows
            or image_id in selected_ids
            or len(image_id) != 16
            or any(character not in _HEX for character in image_id)
            or not _is_sha256(rank)
        ):
            raise RuntimeError("invalid or duplicate selected identity")
        selected_rows.add(row_index)
        selected_ids.add(image_id)
    scientific_by_row: dict[int, dict[str, Any]] = {}
    partition_counts = [0] * PARTITION_COUNT
    for row in scientific:
        row_index = int(row.get("row_index", -1))
        image_id = str(row.get("image_id") or "")
        partition = int(row.get("partition", -1))
        if (
            row_index in scientific_by_row
            or row_index not in selected_rows
            or image_id not in selected_ids
            or not 0 <= partition < PARTITION_COUNT
            or not _is_sha256(row.get("selection_rank_sha256"))
        ):
            raise RuntimeError("invalid scientific manifest identity")
        scientific_by_row[row_index] = row
        partition_counts[partition] += 1
    if partition_counts != EXPECTED_PARTITION_COUNTS:
        raise RuntimeError("scientific partition count drift")
    for partition in range(PARTITION_COUNT):
        rows = _read_jsonl(root / f"partition_{partition:02d}.jsonl")
        if len(rows) != EXPECTED_PARTITION_COUNTS[partition]:
            raise RuntimeError(f"partition {partition} denominator drift")
        if rows != [
            row
            for row in scientific
            if int(row["partition"]) == partition
        ]:
            raise RuntimeError(f"partition {partition} order/content drift")
    return {
        "status": receipt["status"],
        "selected_count": len(selected),
        "scientific_count": len(scientific),
        "partition_counts": partition_counts,
        "macrofold_counts": EXPECTED_MACROFOLD_COUNTS,
        "full_gate_authorized": False,
        "receipt_sha256": expected_self,
        "scientific_manifest_sha256": SCIENTIFIC_MANIFEST_SHA256,
    }


def verify_execution_authorization(
    path: Path,
    expected_file_sha256: str,
    required_scope: str,
) -> dict[str, Any]:
    """Require an external, hash-bound one-shot approval before image access."""
    path = Path(path)
    if not _is_sha256(expected_file_sha256) or sha256_file(path) != expected_file_sha256:
        raise RuntimeError("full-gate authorization file SHA-256 mismatch")
    payload = _read_json(path)
    if not verify_stable_payload(payload):
        raise RuntimeError("full-gate authorization stable replay failed")
    scopes = payload.get("scope")
    if not isinstance(scopes, list) or required_scope not in scopes:
        raise RuntimeError(f"authorization does not grant scope: {required_scope}")
    if (
        payload.get("schema") != AUTHORIZATION_SCHEMA
        or payload.get("status") != "APPROVED_FULL_EXTERNAL_GATE_ONCE"
        or payload.get("authorized") is not True
        or payload.get("candidate_stable_payload_sha256")
        != CANDIDATE_STABLE_PAYLOAD_SHA256
        or payload.get("scientific_manifest_sha256")
        != SCIENTIFIC_MANIFEST_SHA256
        or payload.get("source_object_sha256") != SOURCE_OBJECT_SHA256
        or payload.get("run_once") is not True
        or payload.get("retuning_authorized") is not False
        or payload.get("post_outcome_retry_authorized") is not False
        or not isinstance(payload.get("execution_id"), str)
        or not 8 <= len(payload["execution_id"]) <= 96
        or not _is_sha256(payload.get("authorization_nonce_sha256"))
    ):
        raise RuntimeError("full-gate authorization contract mismatch")
    return payload


def canonical_pixel_sha256(image: Any) -> str:
    """Hash canonical decoded RGB pixels, dimensions, and mode."""
    rgb = image.convert("RGB")
    header = canonical_json(
        {"schema": "decoded-rgb-pixels/1", "width": rgb.width, "height": rgb.height}
    ).encode("utf-8")
    return sha256_bytes(header + b"\x00" + rgb.tobytes())
