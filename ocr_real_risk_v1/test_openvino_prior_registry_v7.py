from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ocr_real_risk_v1 import openvino_prior_registry_entry_v7 as entry
from ocr_real_risk_v1 import openvino_prior_registry_v7 as implementation
from ocr_real_risk_v1.core import canonical_json, sha256_bytes, sha256_file
from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    RETIRED_CORPORA,
    stable_payload,
    write_hash_manifest,
)


def digest(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def synthetic_spec(source_id: str, corpus: str, rows: int) -> dict:
    return {
        "corpus": corpus,
        "split": source_id,
        "repo": "synthetic/repo",
        "revision": "1" * 40,
        "path": f"data/{source_id}.parquet",
        "source_sha256": digest(f"source:{source_id}"),
        "rows": rows,
        "artifact_id": 1,
        "artifact_sha256": "a" * 64,
        "artifact_kind": "manifest",
        "anchor_count": rows,
    }


def write_source_bundle(
    root: Path,
    *,
    source_id: str,
    corpus: str,
    encoded: list[str],
    pixels: list[str],
) -> dict:
    spec = synthetic_spec(source_id, corpus, len(encoded))
    root.mkdir(parents=True)
    records = [
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
    records_path = root / "physical_records.jsonl"
    records_path.write_text(
        "".join(canonical_json(record) + "\n" for record in records),
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
                "source_url": implementation.source_url(spec),
                "source_sha256": spec["source_sha256"],
                "rows": len(records),
            },
            "source_size_bytes": 100,
            "terminal_evidence": {
                "artifact_id": 1,
                "artifact_sha256": "a" * 64,
                "artifact_kind": "manifest",
                "anchor_count": len(records),
                "internal_hash_manifests_verified": True,
            },
            "counts": {
                "rows": len(records),
                "terminal_anchors_verified": len(records),
                "unique_encoded_sha256": len(set(encoded)),
                "unique_pixel_sha256": len(set(pixels)),
                "duplicate_encoded_rows": len(records) - len(set(encoded)),
                "duplicate_pixel_rows": len(records) - len(set(pixels)),
                "total_encoded_image_bytes": 10 * len(records),
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
    (root / "source_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_hash_manifest(root)
    return spec


class FrozenSpecTests(unittest.TestCase):
    def test_full_population_is_38601_across_thirteen_shards(self):
        self.assertEqual(entry.EXPECTED_TOTAL_ROWS, 38_601)
        self.assertEqual(implementation.EXPECTED_TOTAL_ROWS, 38_601)
        self.assertEqual(len(entry.SOURCE_SPECS), 13)
        self.assertEqual(
            implementation.SOURCE_SPECS['sroie-train']['artifact_sha256'],
            'ada46e3e9a5ac2d0a29c7f2af20ee493959e4114e299f94cfc00218e8076badd',
        )
        self.assertEqual(
            implementation.SOURCE_SPECS['sroie-test']['artifact_sha256'],
            '0dc86b73e14029fd45867ed7bbd2b83e3f6d1f22a0791a0a75371ecd3a841f90',
        )
        self.assertEqual(
            sum(int(spec["rows"]) for spec in entry.SOURCE_SPECS.values()),
            38_601,
        )
        self.assertEqual(
            {spec["corpus"] for spec in entry.SOURCE_SPECS.values()},
            set(RETIRED_CORPORA),
        )

    def test_every_source_and_terminal_artifact_is_hash_pinned(self):
        for source_id in entry.EXPECTED_SOURCE_IDS:
            spec = entry.source_spec(source_id)
            self.assertEqual(len(spec["revision"]), 40)
            self.assertEqual(len(spec["source_sha256"]), 64)
            self.assertEqual(len(spec["artifact_sha256"]), 64)
            self.assertIn(spec["revision"], spec["source_url"])
            self.assertIn(spec["path"], spec["source_url"])
            self.assertGreater(spec["rows"], 0)

    def test_legacy_sroie_path_omission_does_not_weaken_hash_binding(self):
        spec = entry.source_spec("sroie-train")
        dataset = {
            "repo": spec["repo"],
            "revision": spec["revision"],
            "parquet_sha256": spec["source_sha256"],
            "expected_rows": spec["rows"],
        }
        self.assertTrue(entry._dataset_matches(dataset, spec))
        non_sroie = dict(spec)
        non_sroie['corpus'] = 'CORD'
        self.assertFalse(entry._dataset_matches(dataset, non_sroie))
        dataset["parquet_sha256"] = "0" * 64
        self.assertFalse(entry._dataset_matches(dataset, spec))


class ProjectionTests(unittest.TestCase):
    def test_source_fingerprint_projects_only_image_column(self):
        source = inspect.getsource(implementation.fingerprint_source)
        self.assertIn('iter_batches(columns=["image"]', source)
        self.assertNotIn('columns=["image",', source)
        self.assertNotIn('columns=["texts"', source)
        self.assertNotIn("pytesseract", source)
        self.assertNotIn("infer_claim", source)

    def test_combined_registry_declares_zero_openvino_outcomes(self):
        source = inspect.getsource(implementation.build_prior_registry)
        self.assertIn('"openvino_scientific_images_opened": 0', source)
        self.assertIn('"ocr_runs": 0', source)
        self.assertIn('"candidate_inference_runs": 0', source)


class CombinedRegistryTests(unittest.TestCase):
    def test_cross_corpus_decoded_pixel_duplicate_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = [base / "a", base / "b"]
            specs = {
                "a": write_source_bundle(
                    roots[0],
                    source_id="a",
                    corpus="Corpus-A",
                    encoded=[digest("encoded-a")],
                    pixels=[digest("same-pixels")],
                ),
                "b": write_source_bundle(
                    roots[1],
                    source_id="b",
                    corpus="Corpus-B",
                    encoded=[digest("encoded-b")],
                    pixels=[digest("same-pixels")],
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
                registry = entry.build_prior_registry(roots, base / "registry")
                replay = entry.verify_prior_registry(base / "registry")
            self.assertEqual(registry["population_rows"], 2)
            self.assertEqual(registry["unique_encoded_sha256"], 2)
            self.assertEqual(registry["unique_pixel_sha256"], 1)
            self.assertEqual(registry["cross_corpus_duplicate_groups"], 1)
            self.assertTrue(replay["complete"])
            self.assertEqual(replay["openvino_scientific_images_opened"], 0)

    def test_missing_or_duplicate_source_bundle_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "a"
            spec = write_source_bundle(
                root,
                source_id="a",
                corpus="Corpus-A",
                encoded=[digest("encoded-a")],
                pixels=[digest("pixels-a")],
            )
            with (
                mock.patch.dict(implementation.SOURCE_SPECS, {"a": spec}, clear=True),
                mock.patch.object(implementation, "EXPECTED_SOURCE_IDS", ("a", "b")),
                mock.patch.object(implementation, "EXPECTED_TOTAL_ROWS", 2),
            ):
                with self.assertRaises(RuntimeError):
                    entry.build_prior_registry([root], base / "missing")
            with (
                mock.patch.dict(implementation.SOURCE_SPECS, {"a": spec}, clear=True),
                mock.patch.object(implementation, "EXPECTED_SOURCE_IDS", ("a",)),
                mock.patch.object(implementation, "EXPECTED_TOTAL_ROWS", 2),
            ):
                with self.assertRaises(RuntimeError):
                    entry.build_prior_registry([root, root], base / "duplicate")

    def test_registry_replay_detects_record_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "a"
            spec = write_source_bundle(
                root,
                source_id="a",
                corpus="Corpus-A",
                encoded=[digest("encoded-a")],
                pixels=[digest("pixels-a")],
            )
            with (
                mock.patch.dict(implementation.SOURCE_SPECS, {"a": spec}, clear=True),
                mock.patch.object(implementation, "EXPECTED_SOURCE_IDS", ("a",)),
                mock.patch.object(implementation, "EXPECTED_TOTAL_ROWS", 1),
                mock.patch.object(implementation, "RETIRED_CORPORA", ("Corpus-A",)),
            ):
                entry.build_prior_registry([root], base / "registry")
                records = base / "registry" / "physical_records.jsonl"
                records.write_text(records.read_text() + "{}\n", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    entry.verify_prior_registry(base / "registry")


if __name__ == "__main__":
    unittest.main()
