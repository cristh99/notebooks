from __future__ import annotations

import copy
import unittest

from .core import canonical_json, sha256_bytes
from .numeric_consensus_candidate_v6_coru import (
    CANDIDATE_ID,
    CANDIDATE_SCHEMA,
    CORU_REVISION,
    CORU_SOURCE_SEAL_STABLE_SHA256,
    SOURCE_CLOSURE_ALGORITHM,
    V6_DEVELOPMENT_RECORD_STABLE_SHA256,
    V6_GATE_LAB_STABLE_SHA256,
    discover_source_files,
    external_protocol,
    verify_manifest,
)


class NumericConsensusCandidateV6CoruTests(unittest.TestCase):
    def test_protocol_is_schema_first_and_fail_closed(self) -> None:
        protocol = external_protocol()
        self.assertEqual(protocol["dataset"], "abdoelsayed/CORU")
        self.assertEqual(protocol["component"], "Receipt")
        self.assertEqual(protocol["revision"], CORU_REVISION)
        self.assertEqual(
            protocol["schema_files"]["test_json"]["sha256"],
            "f9bd21061515ca79ce1ceecf0837faa8c1f418eaa406fc6d38c6eff012ee6ab7",
        )
        self.assertTrue(
            protocol["test_archive"][
                "download_only_after_schema_and_power_gate"
            ]
        )
        adapter = protocol["schema_adapter"]
        self.assertTrue(adapter["requires_explicit_transcription_field"])
        self.assertTrue(adapter["category_name_is_not_ocr_truth"])
        self.assertEqual(adapter["unknown_or_ambiguous_schema"], "terminal_no_ocr")
        self.assertTrue(adapter["selection_completed_before_ocr"])
        self.assertFalse(protocol["selection"]["uses_ocr"])
        self.assertFalse(protocol["selection"]["uses_candidate_output"])

    def test_v6_policy_is_frozen_before_coru(self) -> None:
        policy = external_protocol()["selective_policy"]
        self.assertEqual(policy["name"], "v6_post_outcome_gate_completion")
        self.assertEqual(policy["branch_1_threshold"], 91.0)
        self.assertEqual(policy["branch_2_threshold"], 93.0)
        self.assertTrue(policy["thresholds_selected_on_opened_wildreceipt"])
        self.assertTrue(policy["frozen_before_coru_schema_opening"])
        self.assertFalse(policy["truth_available_at_inference"])
        self.assertFalse(policy["annotation_geometry_available_at_inference"])

    def test_exact_gates_and_power_gate_are_fixed(self) -> None:
        protocol = external_protocol()
        gates = protocol["exact_gates"]
        self.assertEqual(gates["target_error_reduction"], 10.0)
        self.assertEqual(gates["minimum_selected"], 3000)
        self.assertEqual(gates["minimum_accepted"], 900)
        self.assertEqual(gates["minimum_coverage_lower"], 0.25)
        self.assertEqual(gates["counterfactual_maximum_upper"], 0.01)
        power = protocol["power_gate"]
        self.assertEqual(power["archive_download_requires_selected_at_least"], 3000)
        self.assertEqual(power["archive_download_requires_projected_accepts_at_least"], 900)
        self.assertGreater(power["projected_accepts_if_rate_holds"], 1000)
        self.assertTrue(power["planning_only_not_evidence"])

    def test_source_closure_contains_adapter_evaluator_and_policy(self) -> None:
        files = discover_source_files(__import__("pathlib").Path(__file__).resolve().parents[1])
        self.assertIn(
            "ocr_real_risk_v1/coru_receipt_schema_adapter_v6.py", files
        )
        self.assertIn("ocr_real_risk_v1/coru_receipt_external_v6.py", files)
        self.assertIn(
            "ocr_real_risk_v1/wildreceipt_v6_gate_completion_lab.py", files
        )
        self.assertIn(
            "ocr_real_risk_v1/numeric_consensus_candidate_v6_coru.py", files
        )
        self.assertGreaterEqual(len(files), 15)
        self.assertEqual(SOURCE_CLOSURE_ALGORITHM, "python-ast-local-import-closure-v1")

    def test_identity_constants_are_complete_hashes(self) -> None:
        self.assertEqual(CANDIDATE_SCHEMA, "ocr-numeric-consensus-v6-coru-receipt-candidate/1")
        self.assertEqual(CANDIDATE_ID, "numeric-consensus-v6-coru-receipt")
        for value in (
            CORU_SOURCE_SEAL_STABLE_SHA256,
            V6_DEVELOPMENT_RECORD_STABLE_SHA256,
            V6_GATE_LAB_STABLE_SHA256,
        ):
            self.assertEqual(len(value), 64)
        self.assertEqual(len(CORU_REVISION), 40)

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
