from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from ocr_real_risk_v1.core import canonical_json, sha256_bytes, sha256_file
from ocr_real_risk_v1 import openvino_prior_registry_entry_v7 as entry
from ocr_real_risk_v1 import openvino_prior_registry_v7 as implementation
from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    PRIOR_REGISTRY_SCHEMA,
    RETIRED_CORPORA,
    stable_payload,
    verify_stable_payload,
    write_hash_manifest,
)


def png_bytes(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(buffer, format="JPEG", quality=100)
    return buffer.getvalue()


def named_stable(payload: dict, field: str) -> dict:
    result = dict(payload)
    result.pop(field, None)
    result[field] = sha256_bytes(canonical_json(result).encode("utf-8"))
    return result


def write_manifest_artifact(root: Path, spec: dict, anchors: list[bytes]) -> None:
    records = [
        {
            "row_index": index,
            "image_sha256": sha256_bytes(raw),
        }
        for index, raw in enumerate(anchors)
    ]
    manifest = named_stable(
        {
            "schema": "synthetic-manifest/1",
            "dataset": {
                "repo": spec["repo"],
                "revision": spec["revision"],
                "parquet_sha256": spec["source_sha256"],
                "expected_rows": spec["rows"],
                # Deliberately omit filename to exercise the legacy SROIE rule.
            },
            "records": records,
        },
        "manifest_sha256",
    )
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_hash_manifest(root)


def synthetic_spec(source_id: str, source_sha256: str, rows: int) -> dict:
    return {
        "corpus": "Synthetic",
        "split": source_id,
        "repo": "synthetic/repo",
        "revision": "1" * 40,
        "path": f"data/{source_id}.parquet",
        "source_sha256": source_sha256,
        "rows": rows,
        "artifact_id": 1,
        "artifact_sha256": "a" * 64,
        "artifact_kind": "manifest",
        "anchor_count": rows,
    }


class FrozenSpecificationTests(unittest.TestCase):
    def test_source_spec_is_exact_and_population_sums_to_38459(self):
        self.assertEqual(len(entry.SOURCE_SPECS), 13)
        self.assertEqual(
            sum(int(value["rows"]) for value in entry.SOURCE_SPECS.values()),
            38_459,
        )
        self.assertEqual(
            {value["corpus"] for value in entry.SOURCE_SPECS.values()},
            set(RETIRED_CORPORA),
        )
        for source_id in entry.EXPECTED_SOURCE_IDS:
            spec = entry.source_spec(source_id)
            self.assertIn(spec["revision"], spec["source_url"])
            self.assertIn(spec["path"], spec["source_url"])
            self.assertEqual(len(spec["source_sha256"]), 64)
            self.assertEqual(len(spec["artifact_sha256"]), 64)

    def test_legacy_sroie_manifest_may_omit_path_but_not_hash(self):
        spec = entry.source_spec("sroie-train")
        dataset = {
            "repo": spec["repo"],
            "revision": spec["revision"],
            "parquet_sha256": spec["source_sha256"],
            "expected_rows": spec["rows"],
        }
        self.assertTrue(entry._dataset_matches(dataset, spec))
        dataset["parquet_sha256"] = "0" * 64
        self.assertFalse(entry._dataset_matches(dataset, spec))


class SourceFingerprintTests(unittest.TestCase):
    def _write_parquet(self, path: Path, images: list[bytes]) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table(
            {
                "image": pa.array(
                    [
                        {"bytes": raw, "path": f"{index}.png"}
                        for index, raw in enumerate(images)
                    ],
                    type=pa.struct(
                        [
                            pa.field("bytes", pa.binary()),
                            pa.field("path", pa.string()),
                        ]
                    ),
                ),
                "forbidden_annotation": ["secret"] * len(images),
            }
        )
        pq.write_table(table, path)

    def test_source_fingerprint_streams_all_rows_and_verifies_anchors(self):
        images = [png_bytes((1, 2, 3)), png_bytes((4, 5, 6))]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.parquet"
            self._write_parquet(source, images)
            spec = synthetic_spec("synthetic-a", sha256_file(source), len(images))
            terminal = root / "terminal"
            terminal.mkdir()
            write_manifest_artifact(terminal, spec, images)
            output = root / "output"
            with mock.patch.dict(
                implementation.SOURCE_SPECS,
                {"synthetic-a": spec},
                clear=False,
            ):
                receipt = entry.fingerprint_source(
                    source_id="synthetic-a",
                    source_file=source,
                    terminal_root=terminal,
                    output_dir=output,
                )
                summary = entry.verify_source_bundle(output)
            self.assertEqual(receipt["counts"]["rows"], 2)
            self.assertEqual(receipt["counts"]["terminal_anchors_verified"], 2)
            self.assertEqual(summary["rows"], 2)
            self.assertFalse(receipt["annotation_columns_read"])
            self.assertEqual(receipt["ocr_runs"], 0)
            self.assertEqual(receipt["openvino_scientific_images_opened"], 0)

    def test_source_fingerprint_rejects_terminal_anchor_drift(self):
        images = [png_bytes((1, 2, 3))]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.parquet"
            self._write_parquet(source, images)
            spec = synthetic_spec("synthetic-b", sha256_file(source), 1)
            terminal = root / "terminal"
            terminal.mkdir()
            write_manifest_artifact(terminal, spec, [png_bytes((9, 9, 9))])
            with mock.patch.dict(
                implementation.SOURCE_SPECS,
                {"synthetic-b": spec},
                clear=False,
            ):
                with self.assertRaises(RuntimeError):
                    entry.fingerprint_source(
                        source_id="synthetic-b",
                        source_file=source,
                        terminal_root=terminal,
                        output_dir=root / "output",
                    )

    def test_fingerprint_projection_names_only_image_column(self):
        import inspect

        source = inspect.getsource(implementation.fingerprint_source)
        self.assertIn('columns=["image"]', source)
        self.assertNotIn('columns=["image",', source)


class CombinedRegistryTests(unittest.TestCase):
    def _source_bundle(
        self,
        root: Path,
        source_id: str,
        corpus: str,
        encoded: list[str],
        pixels: list[str],
    ) -> None:
        spec = {
            "corpus": corpus,
            "split": source_id,
            "repo": "synthetic/repo",
            "revision": "1" * 40,
            "path": f"data/{source_id}.parquet",
            "source_sha256": sha256_bytes(source_id.encode()),
            "rows": len(encoded),
            "artifact_id": 1,
            "artifact_sha256": "a" * 64,
            "artifact_kind": "manifest",
            "anchor_count": len(encoded),
        }
        root.mkdir(parents=True)
        rows = [
            {
                "source_id": source_id,
                "corpus": corpus,
                "split": source_id,
                "row_index": index,
                "image_path": f"{index}.img",
                "encoded_sha256": encoded[index],
                "pixel_sha256": pixels[index],
                "encoded_bytes": 10,
                "width": 4,
                "height": 3,
                "mode": "RGB",
                "terminal_anchor_verified": True,
            }
            for index in range(len(encoded))
        ]
        (root / "physical_records.jsonl").write_text(
            "".join(canonical_json(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        receipt = stable_payload(
            {
                "schema": implementation.SOURCE_RECEIPT_SCHEMA,
                "status": implementation.SOURCE_STATUS,
                "source": {
                    "source_id": source_id,
                    "corpus": corpus,
                    "split": source_id,
                    "repo": spec["repo"],
                    "revision": spec["revision"],
                    "path": spec["path"],
                    "source_url": entry.source_url(spec),
                    "source_sha256": spec["source_sha256"],
                    "rows": len(rows),
                },
                "source_size_bytes": 100,
                "terminal_evidence": {
                    "artifact_id": 1,
                    "artifact_sha256": "a" * 64,
                    "artifact_kind": "manifest",
                    "anchor_count": len(rows),
                    "internal_hash_manifests_verified": True,
                },
                "counts": {
                    "rows": len(rows),
                    "terminal_anchors_verified": len(rows),
                    "unique_encoded_sha256": len(set(encoded)),
                    "unique_pixel_sha256": len(set(pixels)),
                    "duplicate_encoded_rows": len(rows) - len(set(encoded)),
                    "duplicate_pixel_rows": len(rows) - len(set(pixels)),
                    "total_encoded_image_bytes": 10 * len(rows),
                },
                "records_sha256": sha256_file(root / "physical_records.jsonl"),
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
        (root / "source_receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_hash_manifest(root)
        return spec

    def test_combined_registry_detects_cross_corpus_pixel_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = [base / "a", base / "b"]
            specs = {
                "a": self._source_bundle(
                    roots[0],
                    "a",
                    "Corpus-A",
                    [sha256_bytes(b"a")],
                    [sha256_bytes(b"same-pixels")],
                ),
                "b": self._source_bundle(
                    roots[1],
                    "b",
                    "Corpus-B",
                    [sha256_bytes(b"b")],
                    [sha256_bytes(b"same-pixels")],
                ),
            }
            with (
                mock.patch.dict(implementation.SOURCE_SPECS, specs, clear=True),
                mock.patch.object(implementation, "EXPECTED_SOURCE_IDS", ("a", "b")),
                mock.patch.object(implementation, "EXPECTED_TOTAL_ROWS", 2),
                mock.patch.object(
                    implementation,
                    "RETIRED_CORPORA",
                    ("Corpus-A", "Corpus-B"),
                ),
            ):
                registry = entry.build_prior_registry(roots, base / "combined")
                summary = entry.verify_prior_registry(base / "combined")
            self.assertEqual(registry["population_rows"], 2)
            self.assertEqual(registry["unique_encoded_sha256"], 2)
            self.assertEqual(registry["unique_pixel_sha256"], 1)
            self.assertEqual(registry["cross_corpus_duplicate_groups"], 1)
            self.assertTrue(summary["complete"])
            self.assertEqual(summary["openvino_scientific_images_opened"], 0)

    def test_combined_registry_rejects_missing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "a"
            spec = self._source_bundle(
                root,
                "a",
                "Corpus-A",
                [sha256_bytes(b"a")],
                [sha256_bytes(b"pa")],
            )
            with (
                mock.patch.dict(implementation.SOURCE_SPECS, {"a": spec}, clear=True),
                mock.patch.object(implementation, "EXPECTED_SOURCE_IDS", ("a", "b")),
                mock.patch.object(implementation, "EXPECTED_TOTAL_ROWS", 2),
            ):
                with self.assertRaises(RuntimeError):
                    entry.build_prior_registry([root], base / "combined")


class MetadataOnlyTests(unittest.TestCase):
    def test_cocotext_terminal_contract_requires_zero_prior_image_opening(self):
        spec = entry.source_spec("cocotext")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "v7-evidence"
            evidence.mkdir()
            census = stable_payload(
                {
                    "schema": "ocr-cocotext-v7-metadata-census/1",
                    "dataset": {
                        "id": spec["repo"],
                        "revision": spec["revision"],
                        "source_path": spec["path"],
                        "source_sha256": spec["source_sha256"],
                    },
                    "census": {"row_count": spec["rows"]},
                    "decision": {
                        "image_bytes_opened": False,
                        "ocr_executed": False,
                        "candidate_inference_executed": False,
                        "verdict": "COCOTEXT_V7_TERMINAL_NO_FULL_DOWNLOAD",
                    },
                }
            )
            (evidence / "cocotext_v7_metadata_census.json").write_text(
                json.dumps(census, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            write_hash_manifest(evidence)
            anchors, terminal = entry.verify_terminal_artifact(root, "cocotext")
            self.assertEqual(anchors, {})
            self.assertEqual(terminal["anchor_count"], 0)
            census["decision"]["image_bytes_opened"] = True
            census = stable_payload(
                {
                    key: value
                    for key, value in census.items()
                    if key != "stable_payload_sha256"
                }
            )
            (evidence / "cocotext_v7_metadata_census.json").write_text(
                json.dumps(census, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            write_hash_manifest(evidence)
            with self.assertRaises(RuntimeError):
                entry.verify_terminal_artifact(root, "cocotext")


if __name__ == "__main__":
    unittest.main()
