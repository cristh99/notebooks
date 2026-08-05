from __future__ import annotations

import copy
import unittest

from .cord_detector_crops_v4 import SELECTED_CONFIGURATION
from .core import canonical_json, sha256_bytes
from .numeric_consensus_candidate_v4_ocr import (
    CANDIDATE_ID,
    CANDIDATE_SCHEMA,
    CORU_OCR_SOURCE_SEAL_STABLE_SHA256,
    CORU_REVISION,
    EXPECTED_SPLITS,
    SOURCE_FILES,
    external_protocol,
    verify_manifest,
)


class NumericConsensusCandidateV4OcrTests(unittest.TestCase):
    def test_protocol_binds_all_splits_and_ascii_scope(self) -> None:
        protocol = external_protocol()
        self.assertEqual(protocol["dataset"], "abdoelsayed/CORU")
        self.assertEqual(protocol["component"], "OCR")
        self.assertEqual(protocol["revision"], CORU_REVISION)
        self.assertEqual(protocol["expected_images"], EXPECTED_SPLITS)
        self.assertEqual(protocol["expected_total_images"], 30000)
        self.assertTrue(protocol["selection"]["all_three_published_splits"])
        self.assertTrue(protocol["selection"]["only_ascii_digit_glyphs"])
        self.assertTrue(protocol["selection"]["unicode_non_ascii_digits_out_of_scope"])
        self.assertFalse(protocol["selection"]["selection_uses_ocr"])
        self.assertFalse(protocol["selection"]["selection_uses_candidate_outcome"])
        self.assertEqual(
            protocol["candidate"]["detector_configuration"],
            SELECTED_CONFIGURATION,
        )
        self.assertFalse(protocol["candidate"]["truth_available_at_inference"])
        self.assertFalse(protocol["candidate"]["threshold_change_after_outcomes"])
        self.assertEqual(protocol["exact_gates"]["target_error_reduction"], 10.0)
        self.assertEqual(
            protocol["exact_gates"]["minimum_selected_physical_pairs"],
            3000,
        )
        self.assertEqual(protocol["exact_gates"]["minimum_accepted"], 900)
        self.assertEqual(protocol["runtime"]["partitions"], 60)
        self.assertFalse(protocol["claim_limits"]["general_ocr_superiority_claimed"])
        self.assertFalse(protocol["claim_limits"]["arabic_digit_superiority_claimed"])
        self.assertFalse(
            protocol["claim_limits"]["honduras_production_readiness_claimed"]
        )

    def test_source_set_includes_frozen_archive_adapter(self) -> None:
        self.assertIn("ocr_real_risk_v1/coru_ocr_archive.py", SOURCE_FILES)
        self.assertIn(
            "ocr_real_risk_v1/numeric_consensus_candidate_v4_ocr.py",
            SOURCE_FILES,
        )
        self.assertEqual(len(CORU_OCR_SOURCE_SEAL_STABLE_SHA256), 64)
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
