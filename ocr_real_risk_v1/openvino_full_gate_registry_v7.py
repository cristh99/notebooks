"""Physical deduplication registry and hash-bound persistence contracts."""
from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import canonical_json, sha256_bytes, sha256_file
from .openvino_full_gate_contract_v7 import (
    ACTIVE,
    ABSTAIN_DEDUP_OR_INTEGRITY,
    CANDIDATE_STABLE_PAYLOAD_SHA256,
    DEVELOPMENT_ACCEPTANCE_DENOMINATOR,
    DEVELOPMENT_ACCEPTANCE_NUMERATOR,
    EXCLUDED_INTERNAL_DUPLICATE,
    EXCLUDED_PRIOR_OVERLAP,
    MINIMUM_ACTIVE_AFTER_DEDUP,
    MINIMUM_PROJECTED_VERIFIED,
    PARTITION_COUNT,
    PRIOR_REGISTRY_SCHEMA,
    REGISTRY_READY,
    REGISTRY_SCHEMA,
    RETIRED_CORPORA,
    SCIENTIFIC_MANIFEST_SHA256,
    SOURCE_OBJECT_SHA256,
    _HEX,
    _is_sha256,
    _read_json,
    _read_jsonl,
    _write_json,
    _write_jsonl,
    stable_payload,
    verify_hash_manifest,
    verify_stable_payload,
    write_hash_manifest,
)
from .openvino_prior_registry_v7 import (
    EXPECTED_SOURCE_IDS as EXPECTED_PRIOR_SOURCE_IDS,
    EXPECTED_TOTAL_ROWS as EXPECTED_PRIOR_ROWS,
    REGISTRY_STATUS as PRIOR_REGISTRY_STATUS,
    SOURCE_SPECS as PRIOR_SOURCE_SPECS,
)


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def _validate_manifest_row(row: Mapping[str, Any]) -> tuple[int, str, int, str]:
    row_index = int(row.get("row_index", -1))
    image_id = str(row.get("image_id") or "")
    partition = int(row.get("partition", -1))
    rank = str(row.get("selection_rank_sha256") or "")
    if (
        row_index < 0
        or len(image_id) != 16
        or any(character not in _HEX for character in image_id)
        or not 0 <= partition < PARTITION_COUNT
        or not _is_sha256(rank)
    ):
        raise RuntimeError("invalid scientific manifest row")
    return row_index, image_id, partition, rank


def build_physical_registry(
    scientific_manifest: Sequence[Mapping[str, Any]],
    image_records: Sequence[Mapping[str, Any]],
    prior_registry: Mapping[str, Any],
    *,
    minimum_active: int = MINIMUM_ACTIVE_AFTER_DEDUP,
) -> dict[str, Any]:
    """Build a deterministic physical-evidence registry without annotations."""
    if prior_registry.get("complete") is not True:
        raise RuntimeError("prior-corpus fingerprint registry is incomplete")
    prior_encoded = {str(value) for value in prior_registry.get("encoded_sha256", [])}
    prior_pixels = {str(value) for value in prior_registry.get("pixel_sha256", [])}
    if any(not _is_sha256(value) for value in prior_encoded | prior_pixels):
        raise RuntimeError("prior-corpus registry contains invalid SHA-256")

    manifest_by_row: dict[int, dict[str, Any]] = {}
    manifest_ids: set[str] = set()
    for raw in scientific_manifest:
        row_index, image_id, partition, rank = _validate_manifest_row(raw)
        if row_index in manifest_by_row or image_id in manifest_ids:
            raise RuntimeError("duplicate scientific manifest identity")
        manifest_by_row[row_index] = {
            "row_index": row_index,
            "image_id": image_id,
            "partition": partition,
            "selection_rank_sha256": rank,
        }
        manifest_ids.add(image_id)

    records: list[dict[str, Any]] = []
    seen_rows: set[int] = set()
    seen_ids: set[str] = set()
    for raw in image_records:
        row_index = int(raw.get("row_index", -1))
        image_id = str(raw.get("image_id") or "")
        expected = manifest_by_row.get(row_index)
        if (
            expected is None
            or expected["image_id"] != image_id
            or int(raw.get("partition", -1)) != expected["partition"]
            or raw.get("selection_rank_sha256") != expected["selection_rank_sha256"]
            or row_index in seen_rows
            or image_id in seen_ids
        ):
            raise RuntimeError("image identity does not match scientific manifest")
        encoded = str(raw.get("encoded_sha256") or "")
        pixels = str(raw.get("pixel_sha256") or "")
        if not _is_sha256(encoded) or not _is_sha256(pixels):
            raise RuntimeError("image record lacks valid physical fingerprints")
        width, height = int(raw.get("width", 0)), int(raw.get("height", 0))
        encoded_bytes = int(raw.get("encoded_bytes", 0))
        if width <= 0 or height <= 0 or encoded_bytes <= 0 or raw.get("mode") != "RGB":
            raise RuntimeError("image record decode/shape contract failed")
        records.append(
            {
                **expected,
                "encoded_sha256": encoded,
                "pixel_sha256": pixels,
                "encoded_bytes": encoded_bytes,
                "width": width,
                "height": height,
                "mode": "RGB",
            }
        )
        seen_rows.add(row_index)
        seen_ids.add(image_id)
    if seen_rows != set(manifest_by_row) or seen_ids != manifest_ids:
        raise RuntimeError("image registry does not cover exactly the scientific manifest")
    records.sort(key=lambda row: (str(row["image_id"]), int(row["row_index"])))

    disjoint = _DisjointSet(len(records))
    encoded_owner: dict[str, int] = {}
    pixel_owner: dict[str, int] = {}
    for index, row in enumerate(records):
        for fingerprint, owners in (
            (row["encoded_sha256"], encoded_owner),
            (row["pixel_sha256"], pixel_owner),
        ):
            previous = owners.get(str(fingerprint))
            if previous is None:
                owners[str(fingerprint)] = index
            else:
                disjoint.union(index, previous)
    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        groups[disjoint.find(index)].append(index)

    active = 0
    prior_overlap = 0
    internal_duplicates = 0
    group_receipts: list[dict[str, Any]] = []
    for indices in groups.values():
        ordered = sorted(
            indices,
            key=lambda index: (
                records[index]["image_id"],
                records[index]["row_index"],
            ),
        )
        overlaps_prior = any(
            records[index]["encoded_sha256"] in prior_encoded
            or records[index]["pixel_sha256"] in prior_pixels
            for index in ordered
        )
        canonical = ordered[0]
        for index in ordered:
            row = records[index]
            row["physical_group_key"] = sha256_bytes(
                canonical_json(
                    {
                        "encoded_sha256": sorted(
                            {records[item]["encoded_sha256"] for item in ordered}
                        ),
                        "pixel_sha256": sorted(
                            {records[item]["pixel_sha256"] for item in ordered}
                        ),
                    }
                ).encode("utf-8")
            )
            row["canonical_row_index"] = records[canonical]["row_index"]
            row["canonical_image_id"] = records[canonical]["image_id"]
            if overlaps_prior:
                row["disposition"] = EXCLUDED_PRIOR_OVERLAP
                prior_overlap += 1
            elif index == canonical:
                row["disposition"] = ACTIVE
                active += 1
            else:
                row["disposition"] = EXCLUDED_INTERNAL_DUPLICATE
                internal_duplicates += 1
        group_receipts.append(
            {
                "physical_group_key": records[canonical]["physical_group_key"],
                "canonical_row_index": records[canonical]["row_index"],
                "canonical_image_id": records[canonical]["image_id"],
                "member_count": len(ordered),
                "prior_overlap": overlaps_prior,
            }
        )

    records.sort(key=lambda row: int(row["row_index"]))
    active_partition_counts = [0] * PARTITION_COUNT
    for row in records:
        if row["disposition"] == ACTIVE:
            active_partition_counts[int(row["partition"])] += 1
    projected = (
        active
        * DEVELOPMENT_ACCEPTANCE_NUMERATOR
        / DEVELOPMENT_ACCEPTANCE_DENOMINATOR
    )
    power_pass = bool(
        active >= minimum_active and projected >= MINIMUM_PROJECTED_VERIFIED
    )
    return stable_payload(
        {
            "schema": REGISTRY_SCHEMA,
            "status": REGISTRY_READY if power_pass else ABSTAIN_DEDUP_OR_INTEGRITY,
            "candidate_stable_payload_sha256": CANDIDATE_STABLE_PAYLOAD_SHA256,
            "source_object_sha256": SOURCE_OBJECT_SHA256,
            "scientific_manifest_sha256": SCIENTIFIC_MANIFEST_SHA256,
            "scientific_manifest_count": len(scientific_manifest),
            "prior_registry": {
                "complete": True,
                "encoded_fingerprint_count": len(prior_encoded),
                "pixel_fingerprint_count": len(prior_pixels),
                "stable_payload_sha256": prior_registry.get("stable_payload_sha256"),
            },
            "counts": {
                "manifest_rows": len(scientific_manifest),
                "physical_groups": len(groups),
                "active": active,
                "excluded_prior_overlap": prior_overlap,
                "excluded_internal_duplicate": internal_duplicates,
                "active_partition_counts": active_partition_counts,
            },
            "active_count": active,
            "power_gate": {
                "minimum_active_required": minimum_active,
                "minimum_projected_verified": MINIMUM_PROJECTED_VERIFIED,
                "development_acceptance_fraction": (
                    f"{DEVELOPMENT_ACCEPTANCE_NUMERATOR}/"
                    f"{DEVELOPMENT_ACCEPTANCE_DENOMINATOR}"
                ),
                "projected_verified": projected,
                "pass": power_pass,
            },
            "evaluation_authorized": power_pass,
            "selection_uses_annotations": False,
            "ocr_runs": 0,
            "candidate_inference_runs": 0,
            "records": records,
            "physical_groups": sorted(
                group_receipts,
                key=lambda row: (
                    row["canonical_image_id"],
                    row["canonical_row_index"],
                ),
            ),
        }
    )


def _load_prior_registry(path: Path, expected_file_sha256: str) -> dict[str, Any]:
    """Load only a complete, full-population, zero-outcome prior registry."""
    if not _is_sha256(expected_file_sha256) or sha256_file(path) != expected_file_sha256:
        raise RuntimeError("prior-corpus registry file SHA-256 mismatch")
    payload = _read_json(path)
    encoded = payload.get("encoded_sha256")
    pixels = payload.get("pixel_sha256")
    source_ids = payload.get("source_ids")
    receipts = payload.get("source_receipts")
    if (
        payload.get("schema") != PRIOR_REGISTRY_SCHEMA
        or payload.get("status") != PRIOR_REGISTRY_STATUS
        or payload.get("complete") is not True
        or payload.get("scope") != "FULL_PINNED_POPULATION_ALL_IMAGE_ROWS"
        or set(payload.get("corpora") or []) != set(RETIRED_CORPORA)
        or not isinstance(source_ids, list)
        or len(source_ids) != len(EXPECTED_PRIOR_SOURCE_IDS)
        or set(source_ids) != set(EXPECTED_PRIOR_SOURCE_IDS)
        or payload.get("population_rows") != EXPECTED_PRIOR_ROWS
        or payload.get("expected_population_rows") != EXPECTED_PRIOR_ROWS
        or payload.get("image_projection_only") is not True
        or payload.get("annotation_columns_read") is not False
        or payload.get("ocr_runs") != 0
        or payload.get("candidate_inference_runs") != 0
        or payload.get("openvino_scientific_images_opened") != 0
        or not isinstance(encoded, list)
        or not encoded
        or encoded != sorted(set(encoded))
        or not all(_is_sha256(value) for value in encoded)
        or len(encoded) != payload.get("unique_encoded_sha256")
        or not isinstance(pixels, list)
        or not pixels
        or pixels != sorted(set(pixels))
        or not all(_is_sha256(value) for value in pixels)
        or len(pixels) != payload.get("unique_pixel_sha256")
        or not isinstance(receipts, list)
        or len(receipts) != len(EXPECTED_PRIOR_SOURCE_IDS)
        or not verify_stable_payload(payload)
    ):
        raise RuntimeError("prior-corpus fingerprint registry contract failed")
    receipt_ids: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise RuntimeError("prior-corpus source receipt summary is invalid")
        source_id = str(receipt.get("source_id") or "")
        spec = PRIOR_SOURCE_SPECS.get(source_id)
        if (
            spec is None
            or source_id in receipt_ids
            or receipt.get("rows") != spec["rows"]
            or not _is_sha256(receipt.get("stable_payload_sha256"))
            or not _is_sha256(receipt.get("records_sha256"))
        ):
            raise RuntimeError("prior-corpus source receipt identity drift")
        receipt_ids.add(source_id)
    if receipt_ids != set(EXPECTED_PRIOR_SOURCE_IDS):
        raise RuntimeError("prior-corpus source receipt set drift")
    return payload


def _image_id_from_path(value: object) -> str:
    leaf = str(value or "").rsplit("/", 1)[-1]
    image_id = leaf.rsplit(".", 1)[0].lower()
    if len(image_id) != 16 or any(character not in _HEX for character in image_id):
        raise RuntimeError(f"invalid Open Images ImageID path: {value}")
    return image_id


def write_registry_bundle(
    registry: Mapping[str, Any], output_dir: Path
) -> dict[str, Any]:
    """Persist a registry as independently hash-bound receipt plus JSONL tables."""
    if registry.get("schema") != REGISTRY_SCHEMA or not verify_stable_payload(registry):
        raise RuntimeError("cannot persist an invalid physical registry")
    records = [dict(row) for row in registry.get("records") or []]
    groups = [dict(row) for row in registry.get("physical_groups") or []]
    if len(records) != int(registry.get("scientific_manifest_count") or -1):
        raise RuntimeError("registry record denominator drift before persistence")
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)
    _write_jsonl(output_dir / "registry_records.jsonl", records)
    _write_jsonl(output_dir / "physical_groups.jsonl", groups)
    for partition in range(PARTITION_COUNT):
        _write_jsonl(
            output_dir / f"active_partition_{partition:02d}.jsonl",
            (
                row
                for row in records
                if row["disposition"] == ACTIVE
                and int(row["partition"]) == partition
            ),
        )
    table_hashes = {
        path.name: sha256_file(path) for path in sorted(output_dir.glob("*.jsonl"))
    }
    receipt_payload = {
        key: value
        for key, value in registry.items()
        if key not in {"records", "physical_groups", "stable_payload_sha256"}
    }
    receipt_payload["source_registry_stable_payload_sha256"] = registry[
        "stable_payload_sha256"
    ]
    receipt_payload["artifacts"] = table_hashes
    receipt = stable_payload(receipt_payload)
    _write_json(output_dir / "registry_receipt.json", receipt)
    write_hash_manifest(output_dir)
    verify_registry_bundle(output_dir)
    return receipt


def verify_registry_bundle(root: Path) -> dict[str, Any]:
    root = Path(root)
    expected = {
        "registry_receipt.json",
        "registry_records.jsonl",
        "physical_groups.jsonl",
        *(
            f"active_partition_{partition:02d}.jsonl"
            for partition in range(PARTITION_COUNT)
        ),
    }
    verify_hash_manifest(root, exact_files=set(expected))
    receipt = _read_json(root / "registry_receipt.json")
    if (
        receipt.get("schema") != REGISTRY_SCHEMA
        or not verify_stable_payload(receipt)
        or receipt.get("scientific_manifest_sha256") != SCIENTIFIC_MANIFEST_SHA256
        or receipt.get("candidate_stable_payload_sha256")
        != CANDIDATE_STABLE_PAYLOAD_SHA256
    ):
        raise RuntimeError("physical registry receipt contract failed")
    authorization_binding = receipt.get("authorization_binding")
    if authorization_binding is not None and (
        not isinstance(authorization_binding, Mapping)
        or not isinstance(authorization_binding.get("execution_id"), str)
        or not _is_sha256(authorization_binding.get("authorization_nonce_sha256"))
        or not _is_sha256(
            authorization_binding.get("authorization_stable_payload_sha256")
        )
        or not _is_sha256(authorization_binding.get("authorization_file_sha256"))
    ):
        raise RuntimeError("physical registry authorization binding is invalid")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise RuntimeError("physical registry artifact bindings are missing")
    jsonl_files = sorted(path.name for path in root.glob("*.jsonl"))
    if set(artifacts) != set(jsonl_files):
        raise RuntimeError("physical registry artifact file-set drift")
    for name in jsonl_files:
        if artifacts.get(name) != sha256_file(root / name):
            raise RuntimeError(f"physical registry artifact SHA-256 drift: {name}")
    if not _is_sha256(receipt.get("source_registry_stable_payload_sha256")):
        raise RuntimeError("physical registry source stable binding is missing")
    records = _read_jsonl(root / "registry_records.jsonl")
    groups = _read_jsonl(root / "physical_groups.jsonl")
    if len(records) != int(receipt.get("scientific_manifest_count") or -1):
        raise RuntimeError("physical registry denominator drift")
    reconstructed = {
        key: value
        for key, value in receipt.items()
        if key
        not in {
            "stable_payload_sha256",
            "source_registry_stable_payload_sha256",
            "artifacts",
        }
    }
    reconstructed["records"] = records
    reconstructed["physical_groups"] = groups
    if stable_payload(reconstructed)["stable_payload_sha256"] != receipt[
        "source_registry_stable_payload_sha256"
    ]:
        raise RuntimeError("physical registry source stable replay failed")
    active = [row for row in records if row.get("disposition") == ACTIVE]
    if len(active) != int(receipt.get("active_count") or -1):
        raise RuntimeError("physical registry active count drift")
    partition_counts = []
    active_keys = {(int(row["row_index"]), str(row["image_id"])) for row in active}
    observed_keys: set[tuple[int, str]] = set()
    for partition in range(PARTITION_COUNT):
        rows = _read_jsonl(root / f"active_partition_{partition:02d}.jsonl")
        expected_rows = [
            row for row in active if int(row["partition"]) == partition
        ]
        if rows != expected_rows:
            raise RuntimeError("active registry partition content/order mismatch")
        partition_counts.append(len(rows))
        for row in rows:
            key = (int(row["row_index"]), str(row["image_id"]))
            if key in observed_keys:
                raise RuntimeError("active row appears in multiple partitions")
            observed_keys.add(key)
    if observed_keys != active_keys or partition_counts != receipt["counts"][
        "active_partition_counts"
    ]:
        raise RuntimeError("active partition registry coverage drift")
    return {
        "status": receipt["status"],
        "active_count": len(active),
        "partition_counts": partition_counts,
        "stable_payload_sha256": receipt["stable_payload_sha256"],
        "evaluation_authorized": receipt.get("evaluation_authorized") is True,
        "authorization_binding": receipt.get("authorization_binding"),
    }
