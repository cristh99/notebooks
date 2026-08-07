from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    CANDIDATE_STABLE_PAYLOAD_SHA256,
    MODEL_ARTIFACT_ID,
    MODEL_ZIP_SHA256,
    PARTITION_COUNT,
    SCIENTIFIC_MANIFEST_SHA256,
    SOURCE_OBJECT_SHA256,
    stable_payload,
)
from ocr_real_risk_v1.openvino_full_gate_execution_v7 import (
    CAS_STRATEGY,
    MANIFEST_ARTIFACT_ID,
    MANIFEST_ARTIFACT_SHA256,
    claim_execution_once,
    current_code_bundle,
    execution_claim_receipt,
    new_execution_ledger,
    verify_execution_claim,
)


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def authorization_payload() -> dict:
    fields = {
        "schema": "eaat.openvino_v7_full_execution_authorization/1",
        "status": "APPROVED_FULL_EXTERNAL_GATE_ONCE",
        "authorized": True,
        "scope": ["PREPARE_REGISTRY", "EVALUATE_PARTITIONS", "AGGREGATE"],
        "candidate_stable_payload_sha256": CANDIDATE_STABLE_PAYLOAD_SHA256,
        "scientific_manifest_sha256": SCIENTIFIC_MANIFEST_SHA256,
        "source_object_sha256": SOURCE_OBJECT_SHA256,
        "run_once": True,
        "retuning_authorized": False,
        "post_outcome_retry_authorized": False,
        "execution_id": "openvino-v7-production-like-cas-test",
        "authorization_nonce_sha256": h("cas-authorization-nonce"),
        "manifest_artifact_id": MANIFEST_ARTIFACT_ID,
        "manifest_artifact_sha256": MANIFEST_ARTIFACT_SHA256,
        "model_artifact_id": MODEL_ARTIFACT_ID,
        "model_artifact_sha256": MODEL_ZIP_SHA256,
        "partition_count": PARTITION_COUNT,
        "runner_image": "ubuntu-24.04",
        "python_major_minor": "3.11",
        "tesseract_version": "5.3.4",
        "prior_registry_file_sha256": h("prior-registry-file"),
        "prior_registry_stable_payload_sha256": h("prior-registry-stable"),
        "execution_ledger_branch": "openvino-v7-execution-ledger-v1",
        "execution_ledger_path": "openvino-v7/execution-ledger.json",
        "code_bundle": current_code_bundle(),
    }
    seed = new_execution_ledger(fields)
    fields["execution_ledger_initial_stable_payload_sha256"] = seed[
        "stable_payload_sha256"
    ]
    return stable_payload(fields)


def write_json(path: Path, payload: dict) -> str:
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class ExecutionCasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authorization = authorization_payload()
        self.ledger = new_execution_ledger(self.authorization)
        self.parent = "1" * 40
        self.before_blob = "2" * 40
        self.result_commit = "3" * 40
        self.result_blob = "4" * 40

    def claim(self) -> dict:
        return claim_execution_once(
            self.ledger,
            self.authorization,
            github_run_id=987654,
            github_sha="a" * 40,
            ledger_parent_commit_sha=self.parent,
            ledger_blob_sha_before=self.before_blob,
        )

    def test_pre_cas_transition_never_embeds_future_commit(self):
        claimed = self.claim()
        claim = claimed["claim"]
        self.assertEqual(claim["cas_strategy"], CAS_STRATEGY)
        self.assertEqual(claim["ledger_parent_commit_sha"], self.parent)
        self.assertEqual(claim["ledger_blob_sha_before"], self.before_blob)
        self.assertNotIn("ledger_claim_commit_sha", claim)
        self.assertNotIn("ledger_claim_blob_sha", claim)

    def test_real_claim_requires_distinct_post_cas_result(self):
        claimed = self.claim()
        with self.assertRaises(RuntimeError):
            execution_claim_receipt(claimed, self.authorization)
        with self.assertRaises(RuntimeError):
            execution_claim_receipt(
                claimed,
                self.authorization,
                ledger_claim_commit_sha=self.parent,
                ledger_claim_blob_sha=self.result_blob,
            )
        receipt = execution_claim_receipt(
            claimed,
            self.authorization,
            ledger_claim_commit_sha=self.result_commit,
            ledger_claim_blob_sha=self.result_blob,
        )
        self.assertTrue(receipt["claim_commit_is_post_cas_result"])
        self.assertEqual(receipt["ledger_claim_commit_sha"], self.result_commit)
        self.assertEqual(receipt["ledger_claim_blob_sha"], self.result_blob)

    def test_claim_receipt_replays_and_tamper_fails(self):
        claimed = self.claim()
        receipt = execution_claim_receipt(
            claimed,
            self.authorization,
            ledger_claim_commit_sha=self.result_commit,
            ledger_claim_blob_sha=self.result_blob,
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "execution-claim.json"
            digest = write_json(path, receipt)
            verify_execution_claim(path, digest, self.authorization)
            tampered = dict(receipt)
            tampered["ledger_claim_blob_sha"] = self.before_blob
            tampered = stable_payload(
                {
                    key: value
                    for key, value in tampered.items()
                    if key != "stable_payload_sha256"
                }
            )
            digest = write_json(path, tampered)
            with self.assertRaises(RuntimeError):
                verify_execution_claim(path, digest, self.authorization)

    def test_second_claim_and_conflicting_parent_alias_fail(self):
        claimed = self.claim()
        with self.assertRaises(RuntimeError):
            claim_execution_once(
                claimed,
                self.authorization,
                github_run_id=987655,
                github_sha="b" * 40,
                ledger_parent_commit_sha="5" * 40,
                ledger_blob_sha_before="6" * 40,
            )
        with self.assertRaises(RuntimeError):
            claim_execution_once(
                self.ledger,
                self.authorization,
                github_run_id=987656,
                github_sha="c" * 40,
                ledger_parent_commit_sha="7" * 40,
                ledger_blob_sha_before="8" * 40,
                ledger_claim_commit_sha="9" * 40,
            )


if __name__ == "__main__":
    unittest.main()
