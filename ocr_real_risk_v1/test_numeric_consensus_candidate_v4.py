from __future__ import annotations

import copy
import unittest

from .cord_detector_crops_v4 import SELECTED_CONFIGURATION
from .numeric_consensus_candidate_v4 import (
    CANDIDATE_ID,
    CANDIDATE_SCHEMA,
    CORU_REVISION,
    CORU_SOURCE_SEAL_STABLE_SHA256,
    DEVELOPMENT_STABLE_SHA256,
    MODEL_CANDIDATE_STABLE_SHA256,
    MODEL_SHA256,
    external_protocol,
    verify_manifest,
)
from .core import canonical_json, sha256_bytes


class NumericConsensusCandidateV4Tests(unittest.TestCase):
    def test_external_protocol_is_frozen_and_outcome_blind(self) -> None:
        protocol = external_protocol()
        self.assertEqual(protocol["dataset"], "abdoelsayed/CORU")
        self.assertEqual(protocol["component"], "Receipt")
        self.assertEqual(protocol["revision"], CORU_REVISION)
        self.assertEqual(
            protocol["evaluation_files"],
            ["Receipt/labels.txt", "Receipt/test.json", "Receipt/test.zip"],
        )
        self.assertTrue(protocol["selection"]["performed_before_ocr"])
        self.assertFalse(protocol["selection"]["uses_candidate_outcome"])
        self.assertFalse(protocol["selection"]["uses_ocr_output"])
        self.assertEqual(
            protocol["inference"]["candidate_psms"],
            SELECTED_CONFIGURATION["psms"],
        )
        self.assertFalse(protocol["inference"]["truth_available"])
        self.assertFalse(protocol["inference"]["annotation_bbox_available"])
        self.assertFalse(
            protocol["inference"]["threshold_change_after_outcomes"]
        )
        self.assertEqual(
            protocol["exact_gates"]["target_error_reduction"], 10.0
        )
        self.assertEqual(
            protocol["exact_gates"]["minimum_selected_physical_locations"],
            3000,
        )
        self.assertEqual(protocol["exact_gates"]["minimum_accepted"], 900)
        self.assertGreaterEqual(
            protocol["power_plan"]["coru_test_expected_receipts"],
            protocol["power_plan"]["conservative_selected_target"],
        )
        self.assertFalse(
            protocol["post_pass_limit"]["honduras_production_readiness_claimed"]
        )

    def test_frozen_identity_constants_are_full_hashes(self) -> None:
        self.assertEqual(CANDIDATE_SCHEMA, "ocr-numeric-consensus-candidate/4")
        self.assertEqual(CANDIDATE_ID, "numeric-consensus-v4")
        for value in (
            MODEL_SHA256,
            MODEL_CANDIDATE_STABLE_SHA256,
            DEVELOPMENT_STABLE_SHA256,
            CORU_SOURCE_SEAL_STABLE_SHA256,
        ):
            self.assertEqual(len(value), 64)
        self.assertEqual(len(CORU_REVISION), 40)

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
