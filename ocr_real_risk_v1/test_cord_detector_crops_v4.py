from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from .cord_detector_crops_v4 import (
    DETECTOR_DEVELOPMENT_STABLE_PAYLOAD_SHA256,
    INDEX_SCHEMA,
    SELECTED_CONFIGURATION,
    SHARD_SCHEMA,
    _write_hash_manifest,
    aggregate_shards,
)
from .cord_natural_holdout import SHARD_SPECS
from .core import sha256_file
from .sroie_natural_holdout import stable_payload, verify_stable_payload


def make_shard(root: Path, shard_id: str, *, mutate_crop_hash: bool = False) -> None:
    split = SHARD_SPECS[shard_id]["split"]
    crop_dir = root / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_path = crop_dir / f"{shard_id}.png"
    Image.new("L", (32, 16), 255).save(crop_path)
    crop_sha256 = sha256_file(crop_path)
    if mutate_crop_hash:
        crop_sha256 = "0" * 64
    report = stable_payload(
        {
            "schema": SHARD_SCHEMA,
            "status": "POST_OUTCOME_CORD_DEVELOPMENT_ONLY",
            "dataset": {
                "shard_id": shard_id,
                "split": split,
                "filename": SHARD_SPECS[shard_id]["filename"],
            },
            "manifest_sha256": "1" * 64,
            "detector_development_stable_payload_sha256": (
                DETECTOR_DEVELOPMENT_STABLE_PAYLOAD_SHA256
            ),
            "selected_configuration": SELECTED_CONFIGURATION,
            "execution": {
                "selected_locations": 1,
                "detector_eligible_crops": 1,
                "correct_claim_crops": 1,
                "natural_error_crops": 0,
                "guard_accepts_claim": 1,
                "guard_accepts_counterfactual": 0,
                "reasons": {"ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM": 1},
            },
            "runtime": {},
            "records": [
                {
                    "split": split,
                    "key": f"{split}:{shard_id}",
                    "evidence_key": shard_id,
                    "claim": "1234",
                    "truth": "1234",
                    "claim_correct": True,
                    "counterfactual_claim": "1235",
                    "crop_sha256": crop_sha256,
                    "crop_file": f"crops/{crop_path.name}",
                }
            ],
            "decision": {
                "development_crops_complete": True,
                "external_certificate": False,
                "production_ready": False,
                "fresh_external_corpus_required": True,
                "automatic_production_change": False,
            },
            "constraints": {
                "external_spend_usd": 0,
                "production_modified": False,
            },
        },
        "stable_payload_sha256",
    )
    (root / "cord_detector_crops_v4_shard.json").write_text(
        json.dumps(report, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_hash_manifest(root)


class CordDetectorCropsV4Tests(unittest.TestCase):
    def test_selected_configuration_is_frozen_and_outcome_blind(self) -> None:
        self.assertEqual(
            SELECTED_CONFIGURATION["id"],
            "broad-v2-conflict-ok-psm7_any",
        )
        self.assertEqual(SELECTED_CONFIGURATION["psms"], [3, 4, 6, 11, 12])
        self.assertEqual(
            SELECTED_CONFIGURATION["minimum_distinct_psm_votes"], 2
        )
        self.assertFalse(
            SELECTED_CONFIGURATION["uses_truth_for_candidate_construction"]
        )
        self.assertFalse(
            SELECTED_CONFIGURATION[
                "uses_annotation_bbox_for_candidate_construction"
            ]
        )

    def test_aggregate_preserves_six_shards_and_split_separation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shard_roots = []
            for shard_id in SHARD_SPECS:
                shard_root = root / shard_id
                make_shard(shard_root, shard_id)
                shard_roots.append(shard_root)
            output = root / "aggregate"
            result = aggregate_shards(shard_roots, output)
            self.assertEqual(result["schema"], INDEX_SCHEMA)
            self.assertTrue(
                verify_stable_payload(result, "stable_payload_sha256")
            )
            self.assertEqual(result["execution"]["shards"], 6)
            self.assertEqual(result["execution"]["detector_eligible_crops"], 6)
            self.assertEqual(
                result["execution"]["crops_by_split"],
                {"test": 1, "train": 4, "validation": 1},
            )
            self.assertEqual(result["execution"]["natural_error_crops"], 0)
            self.assertEqual(result["execution"]["unique_crop_sha256"], 1)
            self.assertTrue(
                result["decision"]["ready_for_train_holdout_separation"]
            )
            self.assertFalse(result["decision"]["external_certificate"])
            self.assertFalse(result["decision"]["production_ready"])
            self.assertTrue(
                result["decision"]["fresh_external_corpus_required"]
            )
            self.assertTrue((output / "SHA256SUMS.txt").exists())

    def test_crop_hash_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shard_roots = []
            for index, shard_id in enumerate(SHARD_SPECS):
                shard_root = root / shard_id
                make_shard(
                    shard_root,
                    shard_id,
                    mutate_crop_hash=index == 0,
                )
                shard_roots.append(shard_root)
            with self.assertRaisesRegex(RuntimeError, "crop hash mismatch"):
                aggregate_shards(shard_roots, root / "aggregate")


if __name__ == "__main__":
    unittest.main()
