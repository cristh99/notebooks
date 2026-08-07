"""Full-population physical fingerprint registry for OpenVINO v7 deduplication.

The registry covers every image row in the five frozen prior corpora named by
the OpenVINO v7 preregistration: SROIE, CORD, WildReceipt, TextOCR, and
COCO-Text.  Workers read only the image column from exact hash-pinned Parquet
objects, compute encoded-byte and canonical decoded-RGB pixel SHA-256 values,
and cross-check previously opened selected rows against immutable terminal
artifacts.  No annotation column, OCR engine, candidate model, or OpenVINO
scientific image is accessed by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .core import canonical_json, sha256_bytes, sha256_file
from .openvino_full_gate_contract_v7 import (
    PRIOR_REGISTRY_SCHEMA,
    RETIRED_CORPORA,
    _is_sha256,
    _read_json,
    _write_json,
    _write_jsonl,
    canonical_pixel_sha256,
    stable_payload,
    verify_hash_manifest,
    verify_stable_payload,
    write_hash_manifest,
)

SOURCE_RECEIPT_SCHEMA = "eaat.openvino_v7_prior_source_fingerprint/1"
REGISTRY_BUILD_SCHEMA = "eaat.openvino_v7_prior_registry_build/1"
REGISTRY_STATUS = "PASS_FULL_PRIOR_CORPUS_PHYSICAL_REGISTRY"
SOURCE_STATUS = "PASS_SOURCE_FULL_POPULATION_PHYSICAL_FINGERPRINTS"
EXPECTED_TOTAL_ROWS = 38_459

# Exact source and terminal-artifact identities.  Artifact SHA-256 values are
# ZIP digests as emitted by GitHub Actions.  Source URLs are immutable-revision
# URLs and every downloaded object is verified against source_sha256.
SOURCE_SPECS: dict[str, dict[str, Any]] = {
    "sroie-train": {
        "corpus": "SROIE",
        "split": "train",
        "repo": "jsdnrs/ICDAR2019-SROIE",
        "revision": "bffe40c26759f3376ec2b3ae9031dbba54cd587c",
        "path": "data/train-00000-of-00001.parquet",
        "source_sha256": "b18c16b4d8481e5e4537a1700e4616907fe4acd92d6362a7e430b0e866213887",
        "rows": 626,
        "artifact_id": 8_915_849_860,
        "artifact_sha256": "ef59025d9a2304e0d8c626d1964b585286072f681395c9882ed28c6c8fea3046",
        "artifact_kind": "manifest",
        "anchor_count": 537,
    },
    "sroie-test": {
        "corpus": "SROIE",
        "split": "test",
        "repo": "jsdnrs/ICDAR2019-SROIE",
        "revision": "bffe40c26759f3376ec2b3ae9031dbba54cd587c",
        "path": "data/test-00000-of-00001.parquet",
        "source_sha256": "04f8f31b45944cc6e6459a7a95c851a721fc93ffec0a5c29ece9ded734a684c2",
        "rows": 361,
        "artifact_id": 8_915_766_909,
        "artifact_sha256": "e71dbff710cbbb7b519952e83944d16cb7ac04e6e1397307e41a8ac151ef54af",
        "artifact_kind": "manifest",
        "anchor_count": 308,
    },
    "cord-train-0": {
        "corpus": "CORD",
        "split": "train",
        "repo": "naver-clova-ix/cord-v2",
        "revision": "7f0115a4b758a71d6473b8d085751692da2fef98",
        "path": "data/train-00000-of-00004-b4aaeceff1d90ecb.parquet",
        "source_sha256": "da3994eee1bf9bd3c57f0d53a72c3a6812c8696c5ba26245987949ddf73483cc",
        "rows": 200,
        "artifact_id": 8_918_503_743,
        "artifact_sha256": "6067326674ae88c6393b777ef6cdf681676e6643fb07140bf84a14da34d4ec11",
        "artifact_kind": "manifest",
        "anchor_count": 198,
    },
    "cord-train-1": {
        "corpus": "CORD",
        "split": "train",
        "repo": "naver-clova-ix/cord-v2",
        "revision": "7f0115a4b758a71d6473b8d085751692da2fef98",
        "path": "data/train-00001-of-00004-7dbbe248962764c5.parquet",
        "source_sha256": "cce4def16a0d6a6c75f80be712f7494c56c318a8829b712f5c62650155c9e58e",
        "rows": 200,
        "artifact_id": 8_918_496_476,
        "artifact_sha256": "336497f514078b12d86cd36e01dd03956c315fe2bbe75dc493cf6da8cfc7d0f1",
        "artifact_kind": "manifest",
        "anchor_count": 198,
    },
    "cord-train-2": {
        "corpus": "CORD",
        "split": "train",
        "repo": "naver-clova-ix/cord-v2",
        "revision": "7f0115a4b758a71d6473b8d085751692da2fef98",
        "path": "data/train-00002-of-00004-688fe1305a55e5cc.parquet",
        "source_sha256": "591e2db8fe8b1d364b054f46e8c375b7f00e72578914ba46a573b6858162cab2",
        "rows": 200,
        "artifact_id": 8_918_501_385,
        "artifact_sha256": "64c5e66e464b3cf85dcd6dcd938b5b13b216ac7b2f2924baf398722ce2e25599",
        "artifact_kind": "manifest",
        "anchor_count": 199,
    },
    "cord-train-3": {
        "corpus": "CORD",
        "split": "train",
        "repo": "naver-clova-ix/cord-v2",
        "revision": "7f0115a4b758a71d6473b8d085751692da2fef98",
        "path": "data/train-00003-of-00004-2d0cd200555ed7fd.parquet",
        "source_sha256": "1ffd9de8d6fbcee7630fd4cdfedff05b9b7fabc0fae4fc17557c5fe7cf178748",
        "rows": 200,
        "artifact_id": 8_918_503_646,
        "artifact_sha256": "cd0361a0b266481ce9bfd66f34fc3dd914f6b7bc1f1eb96a6e5f04ba5d6bdbe1",
        "artifact_kind": "manifest",
        "anchor_count": 199,
    },
    "cord-validation": {
        "corpus": "CORD",
        "split": "validation",
        "repo": "naver-clova-ix/cord-v2",
        "revision": "7f0115a4b758a71d6473b8d085751692da2fef98",
        "path": "data/validation-00000-of-00001-cc3c5779fe22e8ca.parquet",
        "source_sha256": "0d0f6dac11fdcc549de2746aa9f53136a3bc22a2a1aff2b0b847f7622ad60c15",
        "rows": 100,
        "artifact_id": 8_918_478_802,
        "artifact_sha256": "8b073093ac71a2d2c91950f8e38021e06569c5d7e274dcbe21c7431f00bc671f",
        "artifact_kind": "manifest",
        "anchor_count": 99,
    },
    "cord-test": {
        "corpus": "CORD",
        "split": "test",
        "repo": "naver-clova-ix/cord-v2",
        "revision": "7f0115a4b758a71d6473b8d085751692da2fef98",
        "path": "data/test-00000-of-00001-9c204eb3f4e11791.parquet",
        "source_sha256": "51c65f1788faff392abe2a0b55b023eb23e9be551c509138eaa3a832514224e7",
        "rows": 100,
        "artifact_id": 8_918_476_717,
        "artifact_sha256": "40e8ba564065dec785b0b7df651e2dc706e0cc6ec2926a19359b64a8ec2d3ffe",
        "artifact_kind": "manifest",
        "anchor_count": 100,
    },
    "wildreceipt-train-0": {
        "corpus": "WildReceipt",
        "split": "train",
        "repo": "kaydee/wildreceipt",
        "revision": "cedafaf3c8b0246c9fad68af29324d655715ad12",
        "path": "data/train-00000-of-00002.parquet",
        "source_sha256": "f11bd09c7373df1726aa3fba02b6513c436809b3417c5b85a24cd0dd4226fc07",
        "source_size_bytes": 449_790_572,
        "rows": 634,
        "artifact_id": 8_928_046_292,
        "artifact_sha256": "2556c18bfc9685cce6cb5d659b688a1cde716b617b9ecc7041276c877af05991",
        "artifact_kind": "manifest",
        "anchor_count": 624,
    },
    "wildreceipt-train-1": {
        "corpus": "WildReceipt",
        "split": "train",
        "repo": "kaydee/wildreceipt",
        "revision": "cedafaf3c8b0246c9fad68af29324d655715ad12",
        "path": "data/train-00001-of-00002.parquet",
        "source_sha256": "e988eeff3ad994f77c1c0fed0a85675f5f132f7911cb5574e8439c2661b0cce7",
        "source_size_bytes": 490_390_793,
        "rows": 633,
        "artifact_id": 8_928_237_073,
        "artifact_sha256": "864f32b137edc348c4b6c83549b67d2c6225d82887b8250eceb29b80fbe336bf",
        "artifact_kind": "manifest",
        "anchor_count": 628,
    },
    "wildreceipt-test": {
        "corpus": "WildReceipt",
        "split": "test",
        "repo": "kaydee/wildreceipt",
        "revision": "cedafaf3c8b0246c9fad68af29324d655715ad12",
        "path": "data/test-00000-of-00001.parquet",
        "source_sha256": "43254778a33b83ae65f9a152b2b559a043f4d4239c4d903b4aca315d129efca0",
        "source_size_bytes": 427_468_952,
        "rows": 472,
        "artifact_id": 8_928_150_174,
        "artifact_sha256": "13bf90167330fa9849ce0ec6574774a68a26af576f7e1211dce82afbc01d57dd",
        "artifact_kind": "manifest",
        "anchor_count": 468,
    },
    "textocr": {
        "corpus": "TextOCR",
        "split": "TextOCR",
        "repo": "Yesianrohn/OCR-Data",
        "revision": "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c",
        "path": "data/TextOCR-00000-of-00001.parquet",
        "source_sha256": "f2d50b206923e4bdb70e9200e92b31bd8626acc37466bab8379fa48bb9c62823",
        "source_size_bytes": 6_196_529_116,
        "rows": 21_778,
        "artifact_id": 8_961_886_770,
        "artifact_sha256": "899732a43cfc7f3889d441a8a639993eef58bc2e21d250e51a3a6c93f1b47921",
        "artifact_kind": "textocr-terminal",
        "anchor_count": 4_674,
    },
    "cocotext": {
        "corpus": "COCO-Text",
        "split": "cocotext",
        "repo": "Yesianrohn/OCR-Data",
        "revision": "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c",
        "path": "data/cocotext-00000-of-00001.parquet",
        "source_sha256": "562176cbb803bb7aa140a4537701ef53ebb86e396c8927f9b160227ac49efd48",
        "source_size_bytes": 2_223_323_062,
        "rows": 13_097,
        "artifact_id": 8_974_218_596,
        "artifact_sha256": "7a0671b214d02276ae0e14689915fbd2800dddf95847317b7fb1745e9e6b3361",
        "artifact_kind": "cocotext-metadata",
        "anchor_count": 0,
    },
}

EXPECTED_SOURCE_IDS = tuple(sorted(SOURCE_SPECS))


def source_url(spec: Mapping[str, Any]) -> str:
    return (
        f"https://huggingface.co/datasets/{spec['repo']}/resolve/"
        f"{spec['revision']}/{spec['path']}?download=true"
    )


def source_spec(source_id: str) -> dict[str, Any]:
    if source_id not in SOURCE_SPECS:
        raise RuntimeError(f"unknown prior-corpus source id: {source_id}")
    spec = dict(SOURCE_SPECS[source_id])
    spec["source_id"] = source_id
    spec["source_url"] = source_url(spec)
    return spec


def _stable_named(payload: Mapping[str, Any], field: str) -> bool:
    expected = str(payload.get(field) or "")
    unsigned = dict(payload)
    unsigned.pop(field, None)
    return _is_sha256(expected) and expected == sha256_bytes(
        canonical_json(unsigned).encode("utf-8")
    )


def _verify_artifact_hashes(root: Path) -> None:
    manifests = sorted(root.rglob("SHA256SUMS.txt"))
    if not manifests:
        raise RuntimeError("terminal artifact contains no SHA256SUMS.txt")
    verified_files = 0
    for manifest in manifests:
        base = manifest.parent
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            if not raw:
                continue
            expected, relative = raw.split("  ", 1)
            target = base / relative
            if not target.is_file() or sha256_file(target) != expected:
                raise RuntimeError(
                    f"terminal artifact internal hash mismatch: {target}"
                )
            verified_files += 1
    if verified_files == 0:
        raise RuntimeError("terminal artifact hash manifests are empty")


def _dataset_matches(dataset: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    path = dataset.get("path", dataset.get("filename", dataset.get("source_path")))
    repo = dataset.get("repo", dataset.get("id"))
    rows = dataset.get("rows", dataset.get("expected_rows"))
    if rows is None:
        rows = dataset.get("source_rows")
    return bool(
        repo == spec["repo"]
        and dataset.get("revision") == spec["revision"]
        and path == spec["path"]
        and dataset.get("parquet_sha256", dataset.get("source_sha256"))
        == spec["source_sha256"]
        and (rows is None or int(rows) == int(spec["rows"]))
    )


def _manifest_anchors(root: Path, spec: Mapping[str, Any]) -> dict[int, str]:
    manifests = [path for path in root.rglob("manifest.json") if path.is_file()]
    if len(manifests) != 1:
        raise RuntimeError("manifest artifact must contain exactly one manifest.json")
    manifest = _read_json(manifests[0])
    if not _stable_named(manifest, "manifest_sha256"):
        raise RuntimeError("terminal manifest stable replay failed")
    dataset = manifest.get("dataset")
    records = manifest.get("records")
    if (
        not isinstance(dataset, Mapping)
        or not _dataset_matches(dataset, spec)
        or not isinstance(records, list)
        or len(records) != spec["anchor_count"]
    ):
        raise RuntimeError("terminal manifest source/denominator contract failed")
    anchors: dict[int, str] = {}
    for record in records:
        row_index = int(record.get("row_index", -1))
        digest = str(record.get("image_sha256") or "")
        if row_index < 0 or row_index in anchors or not _is_sha256(digest):
            raise RuntimeError("invalid or duplicate terminal manifest image anchor")
        anchors[row_index] = digest
    return anchors


def _textocr_anchors(root: Path, spec: Mapping[str, Any]) -> dict[int, str]:
    aggregate_paths = list(root.rglob("textocr_external_aggregate.json"))
    protocol_paths = list(root.rglob("prepared-protocol.json"))
    reports = sorted(root.rglob("partition_report.json"))
    if len(aggregate_paths) != 1 or len(protocol_paths) != 1 or len(reports) != 12:
        raise RuntimeError("TextOCR terminal artifact structure drift")
    aggregate = _read_json(aggregate_paths[0])
    protocol = _read_json(protocol_paths[0])
    if (
        not verify_stable_payload(aggregate)
        or not verify_stable_payload(protocol)
        or not _dataset_matches(aggregate.get("dataset", {}), spec)
        or not _dataset_matches(protocol.get("dataset", {}), spec)
        or aggregate.get("execution", {}).get("selected_unique_images")
        != spec["anchor_count"]
        or protocol.get("execution", {}).get("source_rows") != spec["rows"]
        or protocol.get("execution", {}).get("unique_physical_images")
        != spec["anchor_count"]
    ):
        raise RuntimeError("TextOCR terminal source/denominator contract failed")
    anchors: dict[int, str] = {}
    partitions: set[int] = set()
    for path in reports:
        report = _read_json(path)
        if not verify_stable_payload(report):
            raise RuntimeError("TextOCR partition report stable replay failed")
        partition = int(report.get("partition_id", -1))
        if not 0 <= partition < 12 or partition in partitions:
            raise RuntimeError("TextOCR partition identity drift")
        partitions.add(partition)
        for row in report.get("observations") or []:
            row_index = int(row.get("row_index", -1))
            digest = str(row.get("image_sha256") or "")
            if row_index < 0 or row_index in anchors or not _is_sha256(digest):
                raise RuntimeError("invalid or duplicate TextOCR image anchor")
            anchors[row_index] = digest
    if len(anchors) != spec["anchor_count"] or partitions != set(range(12)):
        raise RuntimeError("TextOCR terminal anchor denominator drift")
    return anchors


def _verify_cocotext_metadata(root: Path, spec: Mapping[str, Any]) -> dict[int, str]:
    paths = list(root.rglob("cocotext_v7_metadata_census.json"))
    if len(paths) != 1:
        raise RuntimeError("COCO-Text terminal census artifact structure drift")
    census = _read_json(paths[0])
    if (
        not verify_stable_payload(census)
        or not _dataset_matches(census.get("dataset", {}), spec)
        or census.get("census", {}).get("row_count") != spec["rows"]
        or census.get("decision", {}).get("image_bytes_opened") is not False
        or census.get("decision", {}).get("ocr_executed") is not False
        or census.get("decision", {}).get("candidate_inference_executed")
        is not False
        or census.get("decision", {}).get("verdict")
        != "COCOTEXT_V7_TERMINAL_NO_FULL_DOWNLOAD"
    ):
        raise RuntimeError("COCO-Text metadata-only terminal contract failed")
    return {}


def verify_terminal_artifact(
    root: Path, source_id: str
) -> tuple[dict[int, str], dict[str, Any]]:
    spec = source_spec(source_id)
    _verify_artifact_hashes(root)
    kind = spec["artifact_kind"]
    if kind == "manifest":
        anchors = _manifest_anchors(root, spec)
    elif kind == "textocr-terminal":
        anchors = _textocr_anchors(root, spec)
    elif kind == "cocotext-metadata":
        anchors = _verify_cocotext_metadata(root, spec)
    else:  # pragma: no cover - frozen table prevents this branch
        raise RuntimeError(f"unsupported terminal artifact kind: {kind}")
    if len(anchors) != spec["anchor_count"]:
        raise RuntimeError("terminal artifact anchor count drift")
    return anchors, {
        "artifact_id": spec["artifact_id"],
        "artifact_sha256": spec["artifact_sha256"],
        "artifact_kind": kind,
        "anchor_count": len(anchors),
        "internal_hash_manifests_verified": True,
    }


def _image_bytes(value: object) -> tuple[bytes, str]:
    path = ""
    if isinstance(value, Mapping):
        path = str(value.get("path") or "")
        value = value.get("bytes")
    if isinstance(value, bytes):
        return value, path
    if isinstance(value, bytearray):
        return bytes(value), path
    if isinstance(value, memoryview):
        return value.tobytes(), path
    raise RuntimeError("prior-corpus image bytes have an unsupported representation")


def fingerprint_source(
    *,
    source_id: str,
    source_file: Path,
    terminal_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    spec = source_spec(source_id)
    source_file = Path(source_file)
    terminal_root = Path(terminal_root)
    if sha256_file(source_file) != spec["source_sha256"]:
        raise RuntimeError("prior-corpus source SHA-256 mismatch")
    expected_size = spec.get("source_size_bytes")
    if expected_size is not None and source_file.stat().st_size != expected_size:
        raise RuntimeError("prior-corpus source byte-size mismatch")
    anchors, terminal = verify_terminal_artifact(terminal_root, source_id)
    try:
        import pyarrow.parquet as pq
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - runtime-only path
        raise RuntimeError("pyarrow==18.1.0 and Pillow==12.2.0 are required") from exc
    parquet = pq.ParquetFile(source_file)
    if parquet.metadata.num_rows != spec["rows"]:
        raise RuntimeError("prior-corpus Parquet row-count drift")
    if "image" not in parquet.schema_arrow.names:
        raise RuntimeError("prior-corpus source lacks image column")

    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)
    records_path = output_dir / "physical_records.jsonl"
    observed_anchors: set[int] = set()
    unique_encoded: set[str] = set()
    unique_pixels: set[str] = set()
    encoded_counts: defaultdict[str, int] = defaultdict(int)
    pixel_counts: defaultdict[str, int] = defaultdict(int)
    row_index = 0
    total_encoded_bytes = 0
    with records_path.open("w", encoding="utf-8") as handle:
        for batch in parquet.iter_batches(columns=["image"], batch_size=8):
            for row in batch.to_pylist():
                raw, image_path = _image_bytes(row.get("image"))
                if not raw:
                    raise RuntimeError(f"empty image bytes at row {row_index}")
                encoded = sha256_bytes(raw)
                expected_anchor = anchors.get(row_index)
                if expected_anchor is not None:
                    if encoded != expected_anchor:
                        raise RuntimeError(
                            f"terminal encoded-image anchor drift at row {row_index}"
                        )
                    observed_anchors.add(row_index)
                try:
                    with Image.open(io.BytesIO(raw)) as opened:
                        image = opened.convert("RGB")
                except Exception as exc:
                    raise RuntimeError(
                        f"prior-corpus image decode failed at row {row_index}"
                    ) from exc
                pixels = canonical_pixel_sha256(image)
                record = {
                    "source_id": source_id,
                    "corpus": spec["corpus"],
                    "split": spec["split"],
                    "row_index": row_index,
                    "image_path": image_path,
                    "encoded_sha256": encoded,
                    "pixel_sha256": pixels,
                    "encoded_bytes": len(raw),
                    "width": image.width,
                    "height": image.height,
                    "mode": "RGB",
                    "terminal_anchor_verified": expected_anchor is not None,
                }
                handle.write(canonical_json(record) + "\n")
                unique_encoded.add(encoded)
                unique_pixels.add(pixels)
                encoded_counts[encoded] += 1
                pixel_counts[pixels] += 1
                total_encoded_bytes += len(raw)
                row_index += 1
                del raw
                if row_index % 256 == 0:
                    print(
                        json.dumps(
                            {
                                "source_id": source_id,
                                "rows_fingerprinted": row_index,
                                "expected_rows": spec["rows"],
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
    if row_index != spec["rows"] or observed_anchors != set(anchors):
        raise RuntimeError("prior-corpus fingerprint or anchor denominator drift")
    duplicate_encoded_rows = sum(count - 1 for count in encoded_counts.values())
    duplicate_pixel_rows = sum(count - 1 for count in pixel_counts.values())
    receipt = stable_payload(
        {
            "schema": SOURCE_RECEIPT_SCHEMA,
            "status": SOURCE_STATUS,
            "source": {
                key: spec[key]
                for key in (
                    "source_id",
                    "corpus",
                    "split",
                    "repo",
                    "revision",
                    "path",
                    "source_url",
                    "source_sha256",
                    "rows",
                )
            },
            "source_size_bytes": source_file.stat().st_size,
            "terminal_evidence": terminal,
            "counts": {
                "rows": row_index,
                "terminal_anchors_verified": len(observed_anchors),
                "unique_encoded_sha256": len(unique_encoded),
                "unique_pixel_sha256": len(unique_pixels),
                "duplicate_encoded_rows": duplicate_encoded_rows,
                "duplicate_pixel_rows": duplicate_pixel_rows,
                "total_encoded_image_bytes": total_encoded_bytes,
            },
            "records_sha256": sha256_file(records_path),
            "projection": ["image"],
            "full_source_object_hash_verified": True,
            "full_population_fingerprinted": True,
            "annotation_columns_read": False,
            "ocr_runs": 0,
            "candidate_inference_runs": 0,
            "openvino_scientific_images_opened": 0,
            "purpose": "PHYSICAL_DEDUP_ONLY",
            "external_spend_usd": 0,
        }
    )
    _write_json(output_dir / "source_receipt.json", receipt)
    write_hash_manifest(output_dir)
    verify_source_bundle(output_dir)
    return receipt


def verify_source_bundle(root: Path) -> dict[str, Any]:
    root = Path(root)
    verify_hash_manifest(
        root,
        exact_files={"source_receipt.json", "physical_records.jsonl"},
    )
    receipt = _read_json(root / "source_receipt.json")
    if (
        receipt.get("schema") != SOURCE_RECEIPT_SCHEMA
        or receipt.get("status") != SOURCE_STATUS
        or not verify_stable_payload(receipt)
        or receipt.get("records_sha256")
        != sha256_file(root / "physical_records.jsonl")
        or receipt.get("annotation_columns_read") is not False
        or receipt.get("ocr_runs") != 0
        or receipt.get("candidate_inference_runs") != 0
        or receipt.get("openvino_scientific_images_opened") != 0
    ):
        raise RuntimeError("prior-corpus source receipt contract failed")
    source_id = str(receipt.get("source", {}).get("source_id") or "")
    spec = source_spec(source_id)
    if (
        receipt.get("source", {}).get("source_sha256") != spec["source_sha256"]
        or receipt.get("source", {}).get("rows") != spec["rows"]
        or receipt.get("counts", {}).get("rows") != spec["rows"]
        or receipt.get("terminal_evidence", {}).get("artifact_id")
        != spec["artifact_id"]
        or receipt.get("terminal_evidence", {}).get("artifact_sha256")
        != spec["artifact_sha256"]
        or receipt.get("terminal_evidence", {}).get("anchor_count")
        != spec["anchor_count"]
    ):
        raise RuntimeError("prior-corpus source receipt frozen identity drift")
    rows = 0
    seen: set[int] = set()
    with (root / "physical_records.jsonl").open("r", encoding="utf-8") as handle:
        for raw in handle:
            row = json.loads(raw)
            row_index = int(row.get("row_index", -1))
            if (
                row.get("source_id") != source_id
                or row_index < 0
                or row_index in seen
                or not _is_sha256(row.get("encoded_sha256"))
                or not _is_sha256(row.get("pixel_sha256"))
                or int(row.get("encoded_bytes", 0)) <= 0
                or int(row.get("width", 0)) <= 0
                or int(row.get("height", 0)) <= 0
                or row.get("mode") != "RGB"
            ):
                raise RuntimeError("invalid prior-corpus physical record")
            seen.add(row_index)
            rows += 1
    if rows != spec["rows"] or seen != set(range(spec["rows"])):
        raise RuntimeError("prior-corpus source bundle row coverage drift")
    return {
        "source_id": source_id,
        "rows": rows,
        "stable_payload_sha256": receipt["stable_payload_sha256"],
        "records_sha256": receipt["records_sha256"],
    }


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, value: int) -> int:
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left, right = self.find(left), self.find(right)
        if left == right:
            return
        if self.rank[left] < self.rank[right]:
            left, right = right, left
        self.parent[right] = left
        if self.rank[left] == self.rank[right]:
            self.rank[left] += 1


def build_prior_registry(
    source_roots: Sequence[Path], output_dir: Path
) -> dict[str, Any]:
    roots_by_id: dict[str, Path] = {}
    summaries: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for root in source_roots:
        summary = verify_source_bundle(root)
        source_id = summary["source_id"]
        if source_id in roots_by_id:
            raise RuntimeError(f"duplicate prior-registry source bundle: {source_id}")
        roots_by_id[source_id] = Path(root)
        summaries.append(summary)
        with (Path(root) / "physical_records.jsonl").open(
            "r", encoding="utf-8"
        ) as handle:
            records.extend(json.loads(line) for line in handle)
    if set(roots_by_id) != set(EXPECTED_SOURCE_IDS):
        raise RuntimeError(
            "prior-registry source-set drift: "
            f"{sorted(set(roots_by_id) ^ set(EXPECTED_SOURCE_IDS))}"
        )
    if len(records) != EXPECTED_TOTAL_ROWS:
        raise RuntimeError("prior-registry total source population drift")

    disjoint = _DisjointSet(len(records))
    encoded_owner: dict[str, int] = {}
    pixel_owner: dict[str, int] = {}
    for index, row in enumerate(records):
        for digest, owners in (
            (str(row["encoded_sha256"]), encoded_owner),
            (str(row["pixel_sha256"]), pixel_owner),
        ):
            previous = owners.get(digest)
            if previous is None:
                owners[digest] = index
            else:
                disjoint.union(index, previous)
    groups: defaultdict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        groups[disjoint.find(index)].append(index)

    duplicate_groups: list[dict[str, Any]] = []
    cross_corpus_groups = 0
    for members in groups.values():
        if len(members) <= 1:
            continue
        ordered = sorted(
            members,
            key=lambda index: (
                records[index]["corpus"],
                records[index]["source_id"],
                int(records[index]["row_index"]),
            ),
        )
        corpora = sorted({str(records[index]["corpus"]) for index in ordered})
        if len(corpora) > 1:
            cross_corpus_groups += 1
        duplicate_groups.append(
            {
                "physical_group_sha256": sha256_bytes(
                    canonical_json(
                        {
                            "encoded_sha256": sorted(
                                {records[index]["encoded_sha256"] for index in ordered}
                            ),
                            "pixel_sha256": sorted(
                                {records[index]["pixel_sha256"] for index in ordered}
                            ),
                        }
                    ).encode("utf-8")
                ),
                "member_count": len(ordered),
                "corpora": corpora,
                "cross_corpus": len(corpora) > 1,
                "members": [
                    {
                        "source_id": records[index]["source_id"],
                        "corpus": records[index]["corpus"],
                        "row_index": records[index]["row_index"],
                        "encoded_sha256": records[index]["encoded_sha256"],
                        "pixel_sha256": records[index]["pixel_sha256"],
                    }
                    for index in ordered
                ],
            }
        )
    duplicate_groups.sort(key=lambda row: row["physical_group_sha256"])
    records.sort(
        key=lambda row: (row["source_id"], int(row["row_index"]))
    )
    encoded = sorted({str(row["encoded_sha256"]) for row in records})
    pixels = sorted({str(row["pixel_sha256"]) for row in records})
    summaries.sort(key=lambda row: row["source_id"])

    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)
    _write_jsonl(output_dir / "physical_records.jsonl", records)
    _write_jsonl(
        output_dir / "cross_corpus_duplicate_groups.jsonl", duplicate_groups
    )
    _write_json(output_dir / "source_bundle_summaries.json", {"sources": summaries})
    registry = stable_payload(
        {
            "schema": PRIOR_REGISTRY_SCHEMA,
            "build_schema": REGISTRY_BUILD_SCHEMA,
            "status": REGISTRY_STATUS,
            "complete": True,
            "scope": "FULL_PINNED_POPULATION_ALL_IMAGE_ROWS",
            "corpora": list(RETIRED_CORPORA),
            "source_ids": list(EXPECTED_SOURCE_IDS),
            "population_rows": len(records),
            "expected_population_rows": EXPECTED_TOTAL_ROWS,
            "unique_encoded_sha256": len(encoded),
            "unique_pixel_sha256": len(pixels),
            "duplicate_physical_groups": len(duplicate_groups),
            "cross_corpus_duplicate_groups": cross_corpus_groups,
            "encoded_sha256": encoded,
            "pixel_sha256": pixels,
            "physical_records_sha256": sha256_file(
                output_dir / "physical_records.jsonl"
            ),
            "duplicate_groups_sha256": sha256_file(
                output_dir / "cross_corpus_duplicate_groups.jsonl"
            ),
            "source_bundle_summaries_sha256": sha256_file(
                output_dir / "source_bundle_summaries.json"
            ),
            "source_receipts": summaries,
            "image_projection_only": True,
            "annotation_columns_read": False,
            "ocr_runs": 0,
            "candidate_inference_runs": 0,
            "openvino_scientific_images_opened": 0,
            "purpose": "OPENVINO_V7_PHYSICAL_DEDUP_ONLY",
            "external_spend_usd": 0,
            "automatic_production_change": False,
        }
    )
    _write_json(output_dir / "prior_registry.json", registry)
    write_hash_manifest(output_dir)
    verify_prior_registry(output_dir)
    return registry


def verify_prior_registry(root: Path) -> dict[str, Any]:
    root = Path(root)
    verify_hash_manifest(
        root,
        exact_files={
            "prior_registry.json",
            "physical_records.jsonl",
            "cross_corpus_duplicate_groups.jsonl",
            "source_bundle_summaries.json",
        },
    )
    registry = _read_json(root / "prior_registry.json")
    if (
        registry.get("schema") != PRIOR_REGISTRY_SCHEMA
        or registry.get("status") != REGISTRY_STATUS
        or registry.get("complete") is not True
        or set(registry.get("corpora") or []) != set(RETIRED_CORPORA)
        or set(registry.get("source_ids") or []) != set(EXPECTED_SOURCE_IDS)
        or registry.get("population_rows") != EXPECTED_TOTAL_ROWS
        or registry.get("expected_population_rows") != EXPECTED_TOTAL_ROWS
        or registry.get("annotation_columns_read") is not False
        or registry.get("ocr_runs") != 0
        or registry.get("candidate_inference_runs") != 0
        or registry.get("openvino_scientific_images_opened") != 0
        or not verify_stable_payload(registry)
    ):
        raise RuntimeError("combined prior-registry contract failed")
    for name, field in (
        ("physical_records.jsonl", "physical_records_sha256"),
        ("cross_corpus_duplicate_groups.jsonl", "duplicate_groups_sha256"),
        ("source_bundle_summaries.json", "source_bundle_summaries_sha256"),
    ):
        if registry.get(field) != sha256_file(root / name):
            raise RuntimeError(f"combined prior-registry hash drift: {name}")
    encoded = registry.get("encoded_sha256")
    pixels = registry.get("pixel_sha256")
    if (
        not isinstance(encoded, list)
        or encoded != sorted(set(encoded))
        or not all(_is_sha256(value) for value in encoded)
        or not isinstance(pixels, list)
        or pixels != sorted(set(pixels))
        or not all(_is_sha256(value) for value in pixels)
        or len(encoded) != registry.get("unique_encoded_sha256")
        or len(pixels) != registry.get("unique_pixel_sha256")
    ):
        raise RuntimeError("combined prior-registry fingerprint-set drift")
    rows = 0
    source_counts: defaultdict[str, int] = defaultdict(int)
    observed_encoded: set[str] = set()
    observed_pixels: set[str] = set()
    with (root / "physical_records.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            source_id = str(row.get("source_id") or "")
            if source_id not in SOURCE_SPECS:
                raise RuntimeError("combined prior-registry contains unknown source")
            source_counts[source_id] += 1
            observed_encoded.add(str(row["encoded_sha256"]))
            observed_pixels.add(str(row["pixel_sha256"]))
            rows += 1
    if (
        rows != EXPECTED_TOTAL_ROWS
        or observed_encoded != set(encoded)
        or observed_pixels != set(pixels)
        or source_counts
        != defaultdict(
            int,
            {
                source_id: int(spec["rows"])
                for source_id, spec in SOURCE_SPECS.items()
            },
        )
    ):
        raise RuntimeError("combined prior-registry population replay failed")
    return {
        "status": registry["status"],
        "complete": True,
        "population_rows": rows,
        "unique_encoded_sha256": len(encoded),
        "unique_pixel_sha256": len(pixels),
        "cross_corpus_duplicate_groups": registry[
            "cross_corpus_duplicate_groups"
        ],
        "stable_payload_sha256": registry["stable_payload_sha256"],
        "openvino_scientific_images_opened": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    print_spec = commands.add_parser("print-spec")
    print_spec.add_argument("--source-id", required=True)
    fingerprint = commands.add_parser("fingerprint-source")
    fingerprint.add_argument("--source-id", required=True)
    fingerprint.add_argument("--source-file", type=Path, required=True)
    fingerprint.add_argument("--terminal-root", type=Path, required=True)
    fingerprint.add_argument("--output-dir", type=Path, required=True)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("source_roots", nargs="+", type=Path)
    aggregate.add_argument("--output-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.command == "print-spec":
        result = source_spec(args.source_id)
    elif args.command == "fingerprint-source":
        result = fingerprint_source(
            source_id=args.source_id,
            source_file=args.source_file,
            terminal_root=args.terminal_root,
            output_dir=args.output_dir,
        )
    elif args.command == "aggregate":
        result = build_prior_registry(args.source_roots, args.output_dir)
    else:
        result = verify_prior_registry(args.root)
    printable = dict(result)
    printable.pop("encoded_sha256", None)
    printable.pop("pixel_sha256", None)
    printable.pop("source_receipts", None)
    print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
