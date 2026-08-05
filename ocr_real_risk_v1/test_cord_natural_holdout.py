from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .cord_aggregate import (
    deduplicate_physical_evidence,
    exact_summary,
)
from .cord_natural_holdout import (
    DATASET_REVISION,
    MANIFEST_SCHEMA,
    SHARD_SPECS,
    build_protocol_bundle,
    quad_bbox,
    select_numeric_annotation,
)
from .sroie_natural_holdout import stable_payload, verify_stable_payload


def _quad(left: int, top: int, right: int, bottom: int) -> dict[str, int]:
    return {
        "x1": left,
        "y1": top,
        "x2": right,
        "y2": top,
        "x3": right,
        "y3": bottom,
        "x4": left,
        "y4": bottom,
    }


class CordNaturalHoldoutTests(unittest.TestCase):
    def test_quad_bbox_uses_all_four_points(self) -> None:
        self.assertEqual(
            quad_bbox(
                {
                    "x1": 11,
                    "y1": 20,
                    "x2": 40,
                    "y2": 18,
                    "x3": 42,
                    "y3": 50,
                    "x4": 9,
                    "y4": 52,
                }
            ),
            (9, 18, 42, 52),
        )

    def test_selection_is_order_independent_and_outcome_blind(self) -> None:
        words = [
            {"text": "12,345", "quad": _quad(10, 10, 60, 30)},
            {"text": "67.890", "quad": _quad(10, 40, 60, 60)},
        ]
        payload = {
            "meta": {
                "split": "train",
                "image_id": 3,
                "image_size": {"width": 100, "height": 100},
            },
            "valid_line": [
                {
                    "words": words,
                    "category": "total.total_price",
                    "group_id": 0,
                    "sub_group_id": 0,
                }
            ],
        }
        first, _ = select_numeric_annotation(
            payload=payload,
            shard_id="train-00000-of-00004",
            split="train",
            key="train:0003",
            image_sha256="a" * 64,
            image_size=(100, 100),
        )
        payload["valid_line"][0]["words"] = list(reversed(words))
        second, _ = select_numeric_annotation(
            payload=payload,
            shard_id="train-00000-of-00004",
            split="train",
            key="train:0003",
            image_sha256="a" * 64,
            image_size=(100, 100),
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        for field in ("truth", "bbox", "selection_rank_sha256"):
            self.assertEqual(first[field], second[field])
        self.assertEqual(len(first["selection_rank_sha256"]), 64)

    def test_numeric_annotation_with_malformed_quad_fails_closed(self) -> None:
        payload = {
            "meta": {
                "split": "train",
                "image_id": 1,
                "image_size": {"width": 100, "height": 100},
            },
            "valid_line": [
                {
                    "words": [
                        {
                            "text": "12,345",
                            "quad": {
                                "x1": 1,
                                "y1": 1,
                                "x2": 20,
                                "y2": 1,
                                "x3": 20,
                                "y3": 20,
                            },
                        }
                    ],
                    "category": "total.total_price",
                }
            ],
        }
        with self.assertRaises(RuntimeError):
            select_numeric_annotation(
                payload=payload,
                shard_id="train-00000-of-00004",
                split="train",
                key="train:0001",
                image_sha256="b" * 64,
                image_size=(100, 100),
            )

    def test_protocol_bundle_requires_exact_six_shards(self) -> None:
        binding = {
            "candidate_id": "digit-forest-v3",
            "artifact_id": 8917522937,
            "artifact_zip_sha256": "0" * 64,
            "source_commit": "1" * 40,
            "model_sha256": "2" * 64,
            "candidate_stable_payload_sha256": "3" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths: list[Path] = []
            for shard_id, spec in SHARD_SPECS.items():
                rows = 200 if spec["split"] == "train" else 100
                manifest = stable_payload(
                    {
                        "schema": MANIFEST_SCHEMA,
                        "dataset": {
                            "repo": "naver-clova-ix/cord-v2",
                            "revision": DATASET_REVISION,
                            "license": "CC-BY-4.0",
                            "split": spec["split"],
                            "shard_id": shard_id,
                            "filename": spec["filename"],
                            "parquet_sha256": shard_id.encode().hex()[:64].ljust(
                                64, "0"
                            ),
                            "rows": rows,
                        },
                        "candidate_binding": binding,
                        "protocol": {},
                        "census": {
                            "rows_with_selected_numeric_location": 0,
                        },
                        "records": [],
                    },
                    "manifest_sha256",
                )
                path = root / f"{shard_id}.json"
                path.write_text(json.dumps(manifest), encoding="utf-8")
                paths.append(path)
            source_files = []
            for shard_id, spec in SHARD_SPECS.items():
                digest = shard_id.encode().hex()[:64].ljust(64, "0")
                source_files.append(
                    {
                        "path": spec["filename"],
                        "size_bytes": 1,
                        "lfs_oid": f"sha256:{digest}",
                        "download_url": (
                            "https://huggingface.co/datasets/"
                            "naver-clova-ix/cord-v2/resolve/"
                            f"{DATASET_REVISION}/{spec['filename']}?download=true"
                        ),
                    }
                )
            source_seal = stable_payload(
                {
                    "schema": "ocr-cord-source-seal/1",
                    "dataset_id": "naver-clova-ix/cord-v2",
                    "resolved_revision": DATASET_REVISION,
                    "files": source_files,
                    "expected_rows": {
                        "train": 800,
                        "validation": 100,
                        "test": 100,
                    },
                    "expected_total_rows": 1000,
                    "total_source_bytes": 6,
                    "outcomes_opened": False,
                    "parquet_rows_read": 0,
                    "purpose": (
                        "freeze external validation source before candidate evaluation"
                    ),
                    "license": "cc-by-4.0",
                },
                "stable_payload_sha256",
            )
            source_seal_path = root / "source_seal.json"
            source_seal_path.write_text(
                json.dumps(source_seal), encoding="utf-8"
            )
            protocol = build_protocol_bundle(
                paths, root / "bundle", source_seal_path
            )
            self.assertTrue(
                verify_stable_payload(protocol, "stable_payload_sha256")
            )
            self.assertEqual(protocol["census"]["published_rows"], 1000)
            self.assertEqual(protocol["status"], "SEALED_BEFORE_CORD_OCR")

    def test_exact_gate_can_certify_only_with_errors_and_coverage(self) -> None:
        rows = []
        for index in range(800):
            eligible = index < 400
            baseline_error = eligible and index < 80
            accepted = eligible and 80 <= index < 380
            rows.append(
                {
                    "tesseract": {
                        "eligible": eligible,
                        "claim_correct": not baseline_error,
                    },
                    "candidate": {
                        "accepted": accepted,
                        "false_accept": False,
                    },
                    "counterfactual": {"false_accept": False},
                }
            )
        summary = exact_summary(rows)
        self.assertTrue(summary["pass"])
        self.assertGreaterEqual(summary["reduction_lower"], 10.0)
        rows[80]["candidate"]["false_accept"] = True
        summary_with_false_accept = exact_summary(rows)
        self.assertFalse(summary_with_false_accept["pass"])

    def test_duplicate_truth_conflict_fails_closed(self) -> None:
        base = {
            "image_sha256": "f" * 64,
            "bbox": [1, 2, 10, 20],
            "annotation_text": "12,345",
            "split": "train",
            "shard_id": "train-00000-of-00004",
            "row_index": 1,
            "key": "train:0001",
            "tesseract": {
                "claim": "12345",
                "eligible": True,
                "eligibility_reason": "ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM",
                "claim_correct": True,
            },
            "candidate": {
                "prediction": "12345",
                "accepted": True,
                "correct_accept": True,
                "false_accept": False,
            },
            "counterfactual": {
                "claim": "12346",
                "prediction": "12345",
                "accepted": False,
                "false_accept": False,
            },
        }
        first = {**base, "truth": "12345"}
        second = {
            **base,
            "truth": "12346",
            "shard_id": "test-00000-of-00001",
            "split": "test",
            "key": "test:0001",
        }
        with self.assertRaises(RuntimeError):
            deduplicate_physical_evidence([first, second])


if __name__ == "__main__":
    unittest.main()
