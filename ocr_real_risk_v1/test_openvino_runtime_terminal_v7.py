from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    AGGREGATE_SCHEMA,
    CANDIDATE_STABLE_PAYLOAD_SHA256,
    FAIL_FULL_EXTERNAL_GATE,
    MODEL_ARTIFACT_ID,
    MODEL_ZIP_SHA256,
    PARTITION_COUNT,
    PASS_FULL_EXTERNAL_GATE,
    SCIENTIFIC_MANIFEST_SHA256,
    SOURCE_OBJECT_SHA256,
    stable_payload,
)
from ocr_real_risk_v1.openvino_full_gate_execution_v7 import (
    MANIFEST_ARTIFACT_ID,
    MANIFEST_ARTIFACT_SHA256,
    claim_execution_once,
    current_code_bundle,
    execution_claim_receipt,
    new_execution_ledger,
)
from ocr_real_risk_v1.openvino_preexecution_gate_v7 import (
    RUNTIME_ROOT_ENV,
    preexecution_source_sha256,
    runtime_setup_source_sha256,
    verify_preexecution_gate,
)
from ocr_real_risk_v1.openvino_runtime_lock_v7 import (
    RUNTIME_ARTIFACT_ID,
    RUNTIME_ARTIFACT_SHA256,
    RUNTIME_IMAGE_OS,
    RUNTIME_IMAGE_VERSION,
    RUNTIME_LOCK_FILE_SHA256,
    RUNTIME_PYTHON_VERSION,
    RUNTIME_STABLE_PAYLOAD_SHA256,
    RUNTIME_TESSERACT_VERSION,
    verifier_source_sha256,
    verify_runtime_lock,
)
from ocr_real_risk_v1.openvino_terminal_ledger_v7 import (
    terminal_execution_receipt,
    terminal_source_sha256,
    terminalize_execution_once,
    verify_terminal_receipt,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def authorization() -> dict:
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
        "execution_id": "openvino-v7-runtime-terminal-unit-test",
        "authorization_nonce_sha256": h("runtime-terminal-nonce"),
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
        "execution_ledger_branch": "openvino-v7-unit-ledger",
        "execution_ledger_path": "openvino-v7/execution-ledger.json",
        "code_bundle": current_code_bundle(),
        "runtime_lock_artifact_id": RUNTIME_ARTIFACT_ID,
        "runtime_lock_artifact_sha256": RUNTIME_ARTIFACT_SHA256,
        "runtime_lock_file_sha256": RUNTIME_LOCK_FILE_SHA256,
        "runtime_lock_stable_payload_sha256": RUNTIME_STABLE_PAYLOAD_SHA256,
        "runtime_image_os": RUNTIME_IMAGE_OS,
        "runtime_image_version": RUNTIME_IMAGE_VERSION,
        "runtime_python_version": RUNTIME_PYTHON_VERSION,
        "runtime_tesseract_version": RUNTIME_TESSERACT_VERSION,
        "runtime_required": True,
        "speed_claim_authorized": False,
        "runtime_verifier_source_sha256": verifier_source_sha256(),
        "runtime_setup_source_sha256": runtime_setup_source_sha256(),
        "terminal_ledger_source_sha256": terminal_source_sha256(),
        "preexecution_gate_source_sha256": preexecution_source_sha256(),
    }
    seed = new_execution_ledger(fields)
    fields["execution_ledger_initial_stable_payload_sha256"] = seed[
        "stable_payload_sha256"
    ]
    return stable_payload(fields)


def claimed_chain(auth: dict) -> tuple[dict, dict]:
    ledger = new_execution_ledger(auth)
    claimed = claim_execution_once(
        ledger,
        auth,
        github_run_id=7001,
        github_sha="a" * 40,
        ledger_parent_commit_sha="1" * 40,
        ledger_blob_sha_before="2" * 40,
    )
    receipt = execution_claim_receipt(
        claimed,
        auth,
        ledger_claim_commit_sha="3" * 40,
        ledger_claim_blob_sha="4" * 40,
    )
    return claimed, receipt


def aggregate(verdict: str = PASS_FULL_EXTERNAL_GATE) -> dict:
    return stable_payload(
        {
            "schema": AGGREGATE_SCHEMA,
            "status": verdict,
            "scientific_verdict": verdict,
            "integrity": {"pass": True, "reasons": []},
            "execution": {"selected": 20_000, "partition_count": 12},
            "automatic_production_change": False,
            "retuning_authorized": False,
            "post_outcome_retry_authorized": False,
        }
    )


class RuntimeLockTests(unittest.TestCase):
    def test_exact_runtime_artifact_replays_without_current_machine_check(self):
        root_value = os.environ.get("OPENVINO_TEST_RUNTIME_LOCK_ROOT")
        if not root_value:
            self.skipTest("exact runtime lock artifact not mounted")
        result = verify_runtime_lock(Path(root_value), authorization(), verify_current=False)
        self.assertEqual(result["artifact_id"], RUNTIME_ARTIFACT_ID)
        self.assertFalse(result["speed_claim_authorized"])

    def test_authorization_substitution_is_rejected_before_bundle_access(self):
        auth = authorization()
        auth["runtime_image_version"] = "substituted"
        with self.assertRaises(RuntimeError):
            verify_runtime_lock(Path("/does/not/matter"), auth, verify_current=False)

    def test_preexecution_requires_env_and_frozen_terminal_source(self):
        auth = authorization()
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                verify_preexecution_gate(auth)
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {RUNTIME_ROOT_ENV: td}, clear=False):
                with mock.patch(
                    "ocr_real_risk_v1.openvino_preexecution_gate_v7.verify_runtime_lock",
                    return_value={"artifact_id": RUNTIME_ARTIFACT_ID},
                ):
                    result = verify_preexecution_gate(auth)
                    self.assertTrue(result["source_access_authorized"])
                    tampered = copy.deepcopy(auth)
                    tampered["terminal_ledger_source_sha256"] = h("tampered")
                    with self.assertRaises(RuntimeError):
                        verify_preexecution_gate(tampered)
                    tampered_setup = copy.deepcopy(auth)
                    tampered_setup["runtime_setup_source_sha256"] = h("tampered-setup")
                    with self.assertRaises(RuntimeError):
                        verify_preexecution_gate(tampered_setup)


class TerminalLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = authorization()
        self.claimed, self.claim = claimed_chain(self.auth)
        self.aggregate = aggregate()

    def terminalize(self) -> dict:
        return terminalize_execution_once(
            self.claimed,
            self.auth,
            self.claim,
            self.aggregate,
            aggregate_artifact_id=8888,
            aggregate_artifact_sha256=h("aggregate-zip"),
            aggregate_file_sha256=h("aggregate-file"),
            github_run_id=7001,
            github_sha="a" * 40,
            ledger_parent_commit_sha="3" * 40,
            ledger_blob_sha_before="4" * 40,
        )

    def test_valid_pass_terminalizes_once_and_receipt_replays(self):
        terminal = self.terminalize()
        receipt = terminal_execution_receipt(
            terminal,
            self.auth,
            self.claim,
            self.aggregate,
            ledger_terminal_commit_sha="5" * 40,
            ledger_terminal_blob_sha="6" * 40,
        )
        verified = verify_terminal_receipt(receipt, self.auth)
        self.assertEqual(verified["scientific_verdict"], PASS_FULL_EXTERNAL_GATE)
        self.assertFalse(verified["post_outcome_retry_authorized"])
        with self.assertRaises(RuntimeError):
            terminalize_execution_once(
                terminal,
                self.auth,
                self.claim,
                self.aggregate,
                aggregate_artifact_id=8888,
                aggregate_artifact_sha256=h("aggregate-zip"),
                aggregate_file_sha256=h("aggregate-file"),
                github_run_id=7001,
                github_sha="a" * 40,
                ledger_parent_commit_sha="3" * 40,
                ledger_blob_sha_before="4" * 40,
            )

    def test_aggregate_or_artifact_substitution_is_rejected(self):
        invalid = aggregate(FAIL_FULL_EXTERNAL_GATE)
        invalid["execution"]["partition_count"] = 11
        invalid = stable_payload(
            {
                key: value
                for key, value in invalid.items()
                if key != "stable_payload_sha256"
            }
        )
        with self.assertRaises(RuntimeError):
            terminalize_execution_once(
                self.claimed,
                self.auth,
                self.claim,
                invalid,
                aggregate_artifact_id=8888,
                aggregate_artifact_sha256=h("aggregate-zip"),
                aggregate_file_sha256=h("aggregate-file"),
                github_run_id=7001,
                github_sha="a" * 40,
                ledger_parent_commit_sha="3" * 40,
                ledger_blob_sha_before="4" * 40,
            )
        with self.assertRaises(RuntimeError):
            terminalize_execution_once(
                self.claimed,
                self.auth,
                self.claim,
                self.aggregate,
                aggregate_artifact_id=8888,
                aggregate_artifact_sha256="not-a-hash",
                aggregate_file_sha256=h("aggregate-file"),
                github_run_id=7001,
                github_sha="a" * 40,
                ledger_parent_commit_sha="3" * 40,
                ledger_blob_sha_before="4" * 40,
            )

    def test_claim_or_terminal_git_identity_substitution_is_rejected(self):
        with self.assertRaises(RuntimeError):
            terminalize_execution_once(
                self.claimed,
                self.auth,
                self.claim,
                self.aggregate,
                aggregate_artifact_id=8888,
                aggregate_artifact_sha256=h("aggregate-zip"),
                aggregate_file_sha256=h("aggregate-file"),
                github_run_id=7002,
                github_sha="a" * 40,
                ledger_parent_commit_sha="3" * 40,
                ledger_blob_sha_before="4" * 40,
            )
        terminal = self.terminalize()
        with self.assertRaises(RuntimeError):
            terminal_execution_receipt(
                terminal,
                self.auth,
                self.claim,
                self.aggregate,
                ledger_terminal_commit_sha="3" * 40,
                ledger_terminal_blob_sha="6" * 40,
            )


if __name__ == "__main__":
    unittest.main()
