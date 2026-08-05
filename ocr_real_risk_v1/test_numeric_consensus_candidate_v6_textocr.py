from __future__ import annotations

import copy
import unittest
from pathlib import Path

from .core import canonical_json, sha256_bytes
from .numeric_consensus_candidate_v6_textocr import (
    CANDIDATE_ID,
    CANDIDATE_SCHEMA,
    DATASET_REVISION,
    SOURCE_CLOSURE_ALGORITHM,
    SOURCE_PATH,
    SOURCE_SHA256,
    SOURCE_SIZE_BYTES,
    TEXTOCR_SOURCE_SEAL_STABLE_SHA256,
    V6_DEVELOPMENT_RECORD_STABLE_SHA256,
    V6_GATE_LAB_STABLE_SHA256,
    discover_source_files,
    external_protocol,
    verify_manifest,
)


class NumericConsensusCandidateV6TextOcrTests(unittest.TestCase):
    def test_protocol_is_schema_first_and_image_blind(self) -> None:
        protocol = external_protocol()
        self.assertEqual(protocol["dataset"], "Yesianrohn/OCR-Data")
        self.assertEqual(protocol["component"], "TextOCR")
        self.assertEqual(protocol["revision"], DATASET_REVISION)
        source = protocol["source_object"]
        self.assertEqual(source["path"], SOURCE_PATH)
        self.assertEqual(source["sha256"], SOURCE_SHA256)
        self.assertEqual(source["size_bytes"], SOURCE_SIZE_BYTES)
        self.assertTrue(source["full_download_only_after_census_power_gate"])
        census = protocol["census"]
        self.assertFalse(census["image_column_read"])
        self.assertEqual(
            census["columns"],
            ["texts", "bboxes", "polygons", "num_text_regions"],
        )
        self.assertTrue(census["bbox_convention_resolved_against_polygon"])
        self.assertEqual(census["unknown_or_ambiguous_geometry"], "fail_closed")
        self.assertTrue(census["one_numeric_risk_unit_per_image_row"])
        self.assertFalse(protocol["selection"]["uses_image_bytes_in_census"])
        self.assertFalse(protocol["selection"]["uses_ocr"])
        self.assertFalse(protocol["selection"]["uses_candidate_output"])

    def test_v6_policy_and_counterfactual_are_frozen(self) -> None:
        protocol = external_protocol()
        policy = protocol["selective_policy"]
        self.assertEqual(policy["name"], "v6_post_outcome_gate_completion")
        self.assertEqual(policy["branch_1_threshold"], 91.0)
        self.assertEqual(policy["branch_2_threshold"], 93.0)
        self.assertTrue(policy["thresholds_selected_on_opened_wildreceipt"])
        self.assertTrue(policy["frozen_before_textocr_opening"])
        self.assertFalse(policy["truth_available_at_inference"])
        self.assertFalse(policy["annotation_geometry_available_at_inference"])
        counterfactual = protocol["counterfactual"]
        self.assertTrue(counterfactual["same_crop_injected_claim_replay"])
        self.assertTrue(counterfactual["generated_before_candidate_inference"])
        self.assertEqual(
            counterfactual["gate"],
            "injected counterfactual claim must be rejected",
        )

    def test_exact_gates_runtime_and_claim_limits_are_fixed(self) -> None:
        protocol = external_protocol()
        gates = protocol["exact_gates"]
        self.assertEqual(gates["target_error_reduction"], 10.0)
        self.assertEqual(gates["minimum_selected"], 3000)
        self.assertEqual(gates["minimum_accepted"], 900)
        self.assertEqual(gates["minimum_coverage_lower"], 0.25)
        self.assertEqual(gates["counterfactual_maximum_upper"], 0.01)
        self.assertEqual(gates["macrofold_count"], 4)
        self.assertEqual(gates["minimum_macrofold_pass_fraction"], 0.75)
        runtime = protocol["runtime"]
        self.assertEqual(runtime["source_closure_algorithm"], SOURCE_CLOSURE_ALGORITHM)
        self.assertEqual(runtime["duckdb_version"], "1.5.4")
        self.assertEqual(runtime["partition_count"], 12)
        self.assertEqual(runtime["macrofold_count"], 4)
        limits = protocol["claim_limits"]
        self.assertTrue(limits["scene_text_numeric_certificate_only"])
        self.assertFalse(limits["receipt_domain_certificate_claimed"])
        self.assertFalse(limits["general_ocr_superiority_claimed"])
        self.assertFalse(limits["external_certificate_claimed"])
        self.assertFalse(limits["honduras_production_readiness_claimed"])

    def test_source_closure_contains_adapter_evaluator_and_policy(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        files = discover_source_files(repository_root)
        required = {
            "ocr_real_risk_v1/textocr_source_seal.py",
            "ocr_real_risk_v1/textocr_adapter_v6.py",
            "ocr_real_risk_v1/textocr_external_v6.py",
            "ocr_real_risk_v1/wildreceipt_v6_gate_completion_lab.py",
            "ocr_real_risk_v1/numeric_consensus_candidate_v6_textocr.py",
        }
        self.assertTrue(required.issubset(set(files)))
        self.assertGreaterEqual(len(files), 15)
        self.assertEqual(SOURCE_CLOSURE_ALGORITHM, "python-ast-local-import-closure-v1")

    def test_identity_constants_are_full_hashes(self) -> None:
        self.assertEqual(CANDIDATE_SCHEMA, "ocr-numeric-consensus-v6-textocr-candidate/1")
        self.assertEqual(CANDIDATE_ID, "numeric-consensus-v6-textocr")
        for value in (
            SOURCE_SHA256,
            TEXTOCR_SOURCE_SEAL_STABLE_SHA256,
            V6_DEVELOPMENT_RECORD_STABLE_SHA256,
            V6_GATE_LAB_STABLE_SHA256,
        ):
            self.assertEqual(len(value), 64)
        self.assertEqual(len(DATASET_REVISION), 40)

    def test_manifest_hash_detects_mutation(self) -> None:
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
