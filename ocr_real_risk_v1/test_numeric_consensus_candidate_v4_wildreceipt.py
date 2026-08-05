from __future__ import annotations

import copy
import unittest

from .cord_detector_crops_v4 import SELECTED_CONFIGURATION
from .core import canonical_json, sha256_bytes
from .numeric_consensus_candidate_v4_wildreceipt import (
    CANDIDATE_ID,
    CANDIDATE_SCHEMA,
    DATASET_REVISION,
    SOURCE_FILES,
    SOURCE_OBJECTS,
    SOURCE_SEAL_STABLE_SHA256,
    external_protocol,
    verify_manifest,
)


class NumericConsensusCandidateV4WildReceiptTests(unittest.TestCase):
    def test_protocol_uses_one_unit_per_unique_receipt(self) -> None:
        protocol = external_protocol()
        self.assertEqual(protocol["dataset"], "kaydee/wildreceipt")
        self.assertEqual(protocol["revision"], DATASET_REVISION)
        self.assertEqual(set(protocol["source_objects"]), set(SOURCE_OBJECTS))
        self.assertEqual(
            protocol["annotation_geometry"]["source_coordinate_space"],
            "layoutlm_normalized_xyxy_0_1000",
        )
        self.assertTrue(
            protocol["annotation_geometry"]["repair_fixed_before_ocr"]
        )
        self.assertFalse(protocol["schema_discovery"]["ocr_executed"])
        self.assertFalse(
            protocol["schema_discovery"]["candidate_inference_executed"]
        )
        self.assertIn("at most one unit", protocol["risk_unit"])
        self.assertTrue(protocol["selection"]["performed_before_ocr"])
        self.assertFalse(protocol["selection"]["uses_candidate_outcome"])
        self.assertFalse(protocol["selection"]["uses_ocr_output"])
        self.assertEqual(
            protocol["selection"]["deduplicate_receipts_across_shards"],
            "decoded image SHA-256",
        )
        self.assertEqual(
            protocol["candidate"]["detector_configuration"],
            SELECTED_CONFIGURATION,
        )
        self.assertFalse(protocol["candidate"]["truth_available_at_inference"])
        self.assertFalse(
            protocol["candidate"]["annotation_bbox_available_at_inference"]
        )
        self.assertFalse(protocol["candidate"]["threshold_change_after_outcomes"])
        self.assertEqual(protocol["exact_gates"]["target_error_reduction"], 10.0)
        self.assertEqual(
            protocol["exact_gates"]["minimum_selected_unique_receipts"],
            1200,
        )
        self.assertEqual(protocol["exact_gates"]["minimum_accepted"], 400)
        power = protocol["power_plan"]
        self.assertEqual(power["maximum_possible_selected_unique_receipts"], 1739)
        self.assertEqual(power["minimum_selected_unique_receipts"], 1200)
        self.assertEqual(power["minimum_selected_for_projected_400_accepts"], 1246)
        self.assertLessEqual(
            power["minimum_selected_for_projected_400_accepts"],
            power["maximum_possible_selected_unique_receipts"],
        )
        self.assertTrue(power["finite_population_feasibility"])
        self.assertTrue(power["underpower_is_an_allowed_terminal_result"])
        self.assertFalse(
            protocol["claim_limits"]["untouched_external_certificate_claimed"]
        )
        self.assertFalse(protocol["claim_limits"]["general_ocr_superiority_claimed"])
        self.assertFalse(
            protocol["claim_limits"]["honduras_production_readiness_claimed"]
        )

    def test_frozen_sources_include_adapter(self) -> None:
        self.assertIn("ocr_real_risk_v1/wildreceipt_adapter.py", SOURCE_FILES)
        self.assertIn("ocr_real_risk_v1/wildreceipt_external.py", SOURCE_FILES)
        self.assertIn(
            "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",
            SOURCE_FILES,
        )
        self.assertEqual(len(SOURCE_SEAL_STABLE_SHA256), 64)
        self.assertEqual(len(DATASET_REVISION), 40)
        self.assertEqual(len(SOURCE_OBJECTS), 3)
        self.assertTrue(
            all(len(row["sha256"]) == 64 for row in SOURCE_OBJECTS.values())
        )

    def test_manifest_stable_hash_detects_mutation(self) -> None:
        payload = {
            "schema": CANDIDATE_SCHEMA,
            "candidate_id": CANDIDATE_ID,
            "decision": {"production_ready": False},
        }
        payload["stable_payload_sha256"] = sha256_bytes(
            canonical_json(payload).encode("utf-8")
        )
        self.assertTrue(verify_manifest(payload))
        mutated = copy.deepcopy(payload)
        mutated["decision"]["production_ready"] = True
        self.assertFalse(verify_manifest(mutated))


if __name__ == "__main__":
    unittest.main()
