from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}")
    write(path, text.replace(old, new, 1))


def replace_block(path: str, start: str, end: str, replacement: str) -> None:
    text = read(path)
    left = text.find(start)
    if left < 0:
        raise RuntimeError(f"{path}: missing block start {start!r}")
    right = text.find(end, left)
    if right < 0:
        raise RuntimeError(f"{path}: missing block end {end!r}")
    if text.find(start, left + 1) >= 0:
        raise RuntimeError(f"{path}: duplicate block start {start!r}")
    write(path, text[:left] + replacement + text[right:])


def patch_prior_registry() -> None:
    path = "ocr_real_risk_v1/openvino_prior_registry_v7.py"
    replace_once(path, "EXPECTED_TOTAL_ROWS = 38_459", "EXPECTED_TOTAL_ROWS = 38_601")
    replace_once(
        path,
        '"ef59025d9a2304e0d8c626d1964b585286072f681395c9882ed28c6c8fea3046"',
        '"ada46e3e9a5ac2d0a29c7f2af20ee493959e4114e299f94cfc00218e8076badd"',
    )
    replace_once(
        path,
        '"e71dbff710cbbb7b519952e83944d16cb7ac04e6e1397307e41a8ac151ef54af"',
        '"0dc86b73e14029fd45867ed7bbd2b83e3f6d1f22a0791a0a75371ecd3a841f90"',
    )
    replace_once(
        path,
        '        and path == spec["path"]\n',
        '        and (\n'
        '            path == spec["path"]\n'
        '            or (path is None and spec.get("corpus") == "SROIE")\n'
        '        )\n',
    )

    entry = '''"""Canonical public entry point for the OpenVINO v7 prior registry.

All frozen identities live in :mod:`openvino_prior_registry_v7`.  This module is
only a stable import/CLI alias; it does not mutate implementation globals.
"""
from __future__ import annotations

from . import openvino_prior_registry_v7 as implementation

SOURCE_SPECS = implementation.SOURCE_SPECS
EXPECTED_SOURCE_IDS = implementation.EXPECTED_SOURCE_IDS
EXPECTED_TOTAL_ROWS = implementation.EXPECTED_TOTAL_ROWS
REGISTRY_STATUS = implementation.REGISTRY_STATUS
source_url = implementation.source_url
source_spec = implementation.source_spec
_dataset_matches = implementation._dataset_matches
verify_terminal_artifact = implementation.verify_terminal_artifact
fingerprint_source = implementation.fingerprint_source
verify_source_bundle = implementation.verify_source_bundle
build_prior_registry = implementation.build_prior_registry
verify_prior_registry = implementation.verify_prior_registry
main = implementation.main


if __name__ == "__main__":
    raise SystemExit(main())
'''
    write("ocr_real_risk_v1/openvino_prior_registry_entry_v7.py", entry)


def patch_prior_loader() -> None:
    path = "ocr_real_risk_v1/openvino_full_gate_registry_v7.py"
    replace_once(
        path,
        ")\n\n\nclass _DisjointSet:",
        ")\nfrom .openvino_prior_registry_v7 import (\n"
        "    EXPECTED_SOURCE_IDS as EXPECTED_PRIOR_SOURCE_IDS,\n"
        "    EXPECTED_TOTAL_ROWS as EXPECTED_PRIOR_ROWS,\n"
        "    REGISTRY_STATUS as PRIOR_REGISTRY_STATUS,\n"
        "    SOURCE_SPECS as PRIOR_SOURCE_SPECS,\n"
        ")\n\n\nclass _DisjointSet:",
    )
    new_block = '''def _load_prior_registry(path: Path, expected_file_sha256: str) -> dict[str, Any]:
    """Load only a complete, full-population, zero-outcome prior registry."""
    if not _is_sha256(expected_file_sha256) or sha256_file(path) != expected_file_sha256:
        raise RuntimeError("prior-corpus registry file SHA-256 mismatch")
    payload = _read_json(path)
    encoded = payload.get("encoded_sha256")
    pixels = payload.get("pixel_sha256")
    source_ids = payload.get("source_ids")
    receipts = payload.get("source_receipts")
    if (
        payload.get("schema") != PRIOR_REGISTRY_SCHEMA
        or payload.get("status") != PRIOR_REGISTRY_STATUS
        or payload.get("complete") is not True
        or payload.get("scope") != "FULL_PINNED_POPULATION_ALL_IMAGE_ROWS"
        or set(payload.get("corpora") or []) != set(RETIRED_CORPORA)
        or not isinstance(source_ids, list)
        or len(source_ids) != len(EXPECTED_PRIOR_SOURCE_IDS)
        or set(source_ids) != set(EXPECTED_PRIOR_SOURCE_IDS)
        or payload.get("population_rows") != EXPECTED_PRIOR_ROWS
        or payload.get("expected_population_rows") != EXPECTED_PRIOR_ROWS
        or payload.get("image_projection_only") is not True
        or payload.get("annotation_columns_read") is not False
        or payload.get("ocr_runs") != 0
        or payload.get("candidate_inference_runs") != 0
        or payload.get("openvino_scientific_images_opened") != 0
        or not isinstance(encoded, list)
        or not encoded
        or encoded != sorted(set(encoded))
        or not all(_is_sha256(value) for value in encoded)
        or len(encoded) != payload.get("unique_encoded_sha256")
        or not isinstance(pixels, list)
        or not pixels
        or pixels != sorted(set(pixels))
        or not all(_is_sha256(value) for value in pixels)
        or len(pixels) != payload.get("unique_pixel_sha256")
        or not isinstance(receipts, list)
        or len(receipts) != len(EXPECTED_PRIOR_SOURCE_IDS)
        or not verify_stable_payload(payload)
    ):
        raise RuntimeError("prior-corpus fingerprint registry contract failed")
    receipt_ids: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise RuntimeError("prior-corpus source receipt summary is invalid")
        source_id = str(receipt.get("source_id") or "")
        spec = PRIOR_SOURCE_SPECS.get(source_id)
        if (
            spec is None
            or source_id in receipt_ids
            or receipt.get("rows") != spec["rows"]
            or not _is_sha256(receipt.get("stable_payload_sha256"))
            or not _is_sha256(receipt.get("records_sha256"))
        ):
            raise RuntimeError("prior-corpus source receipt identity drift")
        receipt_ids.add(source_id)
    if receipt_ids != set(EXPECTED_PRIOR_SOURCE_IDS):
        raise RuntimeError("prior-corpus source receipt set drift")
    return payload


'''
    replace_block(path, "def _load_prior_registry(", "def _image_id_from_path(", new_block)


def patch_execution_contract() -> None:
    path = "ocr_real_risk_v1/openvino_full_gate_execution_v7.py"
    replace_once(
        path,
        "import hashlib\nfrom pathlib import Path",
        "from pathlib import Path",
    )
    replace_once(
        path,
        "from .core import sha256_file",
        "from .core import canonical_json, sha256_bytes, sha256_file",
    )
    replace_once(
        path,
        'CAS_STRATEGY = "github_contents_api_blob_sha_compare_and_swap"',
        'CAS_STRATEGY = "github_git_data_fast_forward_ref_cas"',
    )
    replace_block(
        path,
        "def _synthetic_authorization(",
        "def verify_bound_execution_authorization(",
        '''AUTHORIZATION_COMMITMENT_EXCLUDED = frozenset(
    {"stable_payload_sha256", "execution_ledger_initial_stable_payload_sha256"}
)


def authorization_commitment(authorization: Mapping[str, Any]) -> str:
    """Commit every pre-ledger authorization field without circular hashing."""
    unsigned = {
        key: value
        for key, value in authorization.items()
        if key not in AUTHORIZATION_COMMITMENT_EXCLUDED
    }
    return sha256_bytes(canonical_json(unsigned).encode("utf-8"))


''',
    )
    ledger_block = '''def _ledger_fields(authorization: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": EXECUTION_LEDGER_SCHEMA,
        "status": LEDGER_APPROVED,
        "execution_id": authorization["execution_id"],
        "authorization_nonce_sha256": authorization["authorization_nonce_sha256"],
        "authorization_commitment_sha256": authorization_commitment(authorization),
        "candidate_stable_payload_sha256": authorization[
            "candidate_stable_payload_sha256"
        ],
        "scientific_manifest_sha256": authorization["scientific_manifest_sha256"],
        "source_object_sha256": authorization["source_object_sha256"],
        "manifest_artifact_id": authorization["manifest_artifact_id"],
        "manifest_artifact_sha256": authorization["manifest_artifact_sha256"],
        "model_artifact_id": authorization["model_artifact_id"],
        "model_artifact_sha256": authorization["model_artifact_sha256"],
        "prior_registry_file_sha256": authorization["prior_registry_file_sha256"],
        "prior_registry_stable_payload_sha256": authorization[
            "prior_registry_stable_payload_sha256"
        ],
        "partition_count": authorization["partition_count"],
        "runner_image": authorization["runner_image"],
        "python_major_minor": authorization["python_major_minor"],
        "tesseract_version": authorization["tesseract_version"],
        "authorized_scopes": list(authorization["scope"]),
        "execution_ledger_branch": authorization["execution_ledger_branch"],
        "execution_ledger_path": authorization["execution_ledger_path"],
        "code_bundle": dict(authorization["code_bundle"]),
        "claim_count": 0,
        "terminal": None,
    }


def new_execution_ledger(authorization: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact non-circular ledger seed pinned by authorization."""
    required = (
        "execution_id",
        "authorization_nonce_sha256",
        "candidate_stable_payload_sha256",
        "scientific_manifest_sha256",
        "source_object_sha256",
        "manifest_artifact_id",
        "manifest_artifact_sha256",
        "model_artifact_id",
        "model_artifact_sha256",
        "prior_registry_file_sha256",
        "prior_registry_stable_payload_sha256",
        "partition_count",
        "runner_image",
        "python_major_minor",
        "tesseract_version",
        "scope",
        "execution_ledger_branch",
        "execution_ledger_path",
        "code_bundle",
    )
    if any(key not in authorization for key in required):
        raise RuntimeError("authorization fields are insufficient for ledger seed")
    ledger = stable_payload(_ledger_fields(authorization))
    expected = authorization.get("execution_ledger_initial_stable_payload_sha256")
    if expected is not None and expected != ledger["stable_payload_sha256"]:
        raise RuntimeError("execution ledger seed differs from authorization")
    return ledger


'''
    replace_block(path, "def _ledger_fields(", "def claim_execution_once(", ledger_block)
    claim_block = '''def claim_execution_once(
    ledger: Mapping[str, Any],
    authorization: Mapping[str, Any],
    *,
    github_run_id: int,
    github_sha: str,
    ledger_parent_commit_sha: str,
    ledger_blob_sha_before: str,
) -> dict[str, Any]:
    """Create the pre-CAS transition from the exact authorized seed."""
    expected_seed = new_execution_ledger(authorization)
    if dict(ledger) != expected_seed or not verify_stable_payload(ledger):
        raise RuntimeError("execution authorization is already consumed or mismatched")
    if (
        not isinstance(github_run_id, int)
        or github_run_id <= 0
        or not _is_git_oid(github_sha)
        or not _is_git_oid(ledger_parent_commit_sha)
        or not _is_git_oid(ledger_blob_sha_before)
    ):
        raise RuntimeError("invalid GitHub pre-CAS execution identity")
    return stable_payload(
        {
            **{
                key: value
                for key, value in ledger.items()
                if key != "stable_payload_sha256"
            },
            "status": LEDGER_CLAIMED,
            "claim_count": 1,
            "claim": {
                "github_run_id": github_run_id,
                "github_sha": github_sha,
                "cas_strategy": CAS_STRATEGY,
                "ledger_parent_commit_sha": ledger_parent_commit_sha,
                "ledger_blob_sha_before": ledger_blob_sha_before,
                "previous_ledger_stable_payload_sha256": ledger[
                    "stable_payload_sha256"
                ],
            },
        }
    )


'''
    replace_block(path, "def claim_execution_once(", "def execution_claim_receipt(", claim_block)
    receipt_block = '''def execution_claim_receipt(
    claimed_ledger: Mapping[str, Any],
    authorization: Mapping[str, Any],
    *,
    ledger_claim_commit_sha: str,
    ledger_claim_blob_sha: str,
) -> dict[str, Any]:
    """Bind the verified post-CAS Git result to the exact claimed ledger."""
    if not verify_stable_payload(claimed_ledger):
        raise RuntimeError("claimed ledger is invalid")
    claim = claimed_ledger.get("claim")
    if not isinstance(claim, Mapping):
        raise RuntimeError("claimed ledger lacks claim identity")
    expected_claimed = claim_execution_once(
        new_execution_ledger(authorization),
        authorization,
        github_run_id=int(claim.get("github_run_id", 0)),
        github_sha=str(claim.get("github_sha") or ""),
        ledger_parent_commit_sha=str(claim.get("ledger_parent_commit_sha") or ""),
        ledger_blob_sha_before=str(claim.get("ledger_blob_sha_before") or ""),
    )
    if dict(claimed_ledger) != expected_claimed:
        raise RuntimeError("claimed ledger is not the authorized CAS transition")
    if (
        not _is_git_oid(ledger_claim_commit_sha)
        or not _is_git_oid(ledger_claim_blob_sha)
        or ledger_claim_commit_sha == claim["ledger_parent_commit_sha"]
        or ledger_claim_blob_sha == claim["ledger_blob_sha_before"]
    ):
        raise RuntimeError("invalid or non-advancing post-CAS GitHub identity")
    return stable_payload(
        {
            "schema": EXECUTION_CLAIM_SCHEMA,
            "status": LEDGER_CLAIMED,
            "execution_id": authorization["execution_id"],
            "authorization_stable_payload_sha256": authorization[
                "stable_payload_sha256"
            ],
            "authorization_nonce_sha256": authorization[
                "authorization_nonce_sha256"
            ],
            "authorization_commitment_sha256": authorization_commitment(
                authorization
            ),
            "initial_ledger_stable_payload_sha256": authorization[
                "execution_ledger_initial_stable_payload_sha256"
            ],
            "previous_ledger_stable_payload_sha256": claim[
                "previous_ledger_stable_payload_sha256"
            ],
            "claimed_ledger_stable_payload_sha256": claimed_ledger[
                "stable_payload_sha256"
            ],
            "execution_ledger_branch": authorization["execution_ledger_branch"],
            "execution_ledger_path": authorization["execution_ledger_path"],
            "github_run_id": claim["github_run_id"],
            "github_sha": claim["github_sha"],
            "cas_strategy": claim["cas_strategy"],
            "ledger_parent_commit_sha": claim["ledger_parent_commit_sha"],
            "ledger_blob_sha_before": claim["ledger_blob_sha_before"],
            "ledger_claim_commit_sha": ledger_claim_commit_sha,
            "ledger_claim_blob_sha": ledger_claim_blob_sha,
            "claim_commit_is_post_cas_result": True,
            "branch_fast_forward_verified": True,
            "commit_parent_verified": True,
            "blob_content_verified": True,
            "code_bundle": dict(authorization["code_bundle"]),
            "consumed_once": True,
        }
    )


'''
    replace_block(path, "def execution_claim_receipt(", "def verify_execution_claim(", receipt_block)
    verify_block = '''def verify_execution_claim(
    path: Path,
    expected_file_sha256: str,
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    path = Path(path)
    if not _is_sha256(expected_file_sha256) or sha256_file(path) != expected_file_sha256:
        raise RuntimeError("execution claim file SHA-256 mismatch")
    payload = _read_json(path)
    if (
        payload.get("schema") != EXECUTION_CLAIM_SCHEMA
        or payload.get("status") != LEDGER_CLAIMED
        or payload.get("consumed_once") is not True
        or payload.get("claim_commit_is_post_cas_result") is not True
        or payload.get("branch_fast_forward_verified") is not True
        or payload.get("commit_parent_verified") is not True
        or payload.get("blob_content_verified") is not True
        or payload.get("cas_strategy") != CAS_STRATEGY
        or not verify_stable_payload(payload)
        or payload.get("execution_id") != authorization.get("execution_id")
        or payload.get("authorization_stable_payload_sha256")
        != authorization.get("stable_payload_sha256")
        or payload.get("authorization_nonce_sha256")
        != authorization.get("authorization_nonce_sha256")
        or payload.get("authorization_commitment_sha256")
        != authorization_commitment(authorization)
        or payload.get("initial_ledger_stable_payload_sha256")
        != authorization.get("execution_ledger_initial_stable_payload_sha256")
        or payload.get("previous_ledger_stable_payload_sha256")
        != authorization.get("execution_ledger_initial_stable_payload_sha256")
        or payload.get("execution_ledger_branch")
        != authorization.get("execution_ledger_branch")
        or payload.get("execution_ledger_path")
        != authorization.get("execution_ledger_path")
        or payload.get("code_bundle") != authorization.get("code_bundle")
        or not _is_sha256(payload.get("claimed_ledger_stable_payload_sha256"))
        or not isinstance(payload.get("github_run_id"), int)
        or payload.get("github_run_id") <= 0
        or not _is_git_oid(payload.get("github_sha"))
        or not _is_git_oid(payload.get("ledger_parent_commit_sha"))
        or not _is_git_oid(payload.get("ledger_blob_sha_before"))
        or not _is_git_oid(payload.get("ledger_claim_commit_sha"))
        or not _is_git_oid(payload.get("ledger_claim_blob_sha"))
        or payload.get("ledger_claim_commit_sha")
        == payload.get("ledger_parent_commit_sha")
        or payload.get("ledger_claim_blob_sha")
        == payload.get("ledger_blob_sha_before")
    ):
        raise RuntimeError("execution claim contract failed")
    return payload


'''
    replace_block(path, "def verify_execution_claim(", "def claim_binding(", verify_block)
    replace_once(
        path,
        '        "authorization_file_sha256": authorization_file_sha256,\n',
        '        "authorization_file_sha256": authorization_file_sha256,\n'
        '        "authorization_commitment_sha256": claim[\n'
        '            "authorization_commitment_sha256"\n'
        '        ],\n',
    )
    replace_once(
        path,
        '        "claimed_ledger_stable_payload_sha256": claim[\n'
        '            "claimed_ledger_stable_payload_sha256"\n'
        '        ],\n',
        '        "claimed_ledger_stable_payload_sha256": claim[\n'
        '            "claimed_ledger_stable_payload_sha256"\n'
        '        ],\n'
        '        "execution_ledger_branch": claim["execution_ledger_branch"],\n'
        '        "execution_ledger_path": claim["execution_ledger_path"],\n',
    )


def patch_full_gate_tests() -> None:
    path = "ocr_real_risk_v1/test_openvino_full_gate_v7.py"
    replace_once(
        path,
        '    MANIFEST_ARTIFACT_SHA256,\n)',
        '    MANIFEST_ARTIFACT_SHA256,\n    claim_binding,\n)',
    )
    replace_once(
        path,
        '"execution_id": "openvino-v7-synthetic-test-execution"',
        '"execution_id": "openvino-v7-unit-test-execution"',
    )
    replace_block(
        path,
        "def claim_binding_fixture(",
        "def observation(",
        '''def claim_binding_fixture(authorization: dict) -> tuple[dict, dict]:
    ledger = new_execution_ledger(authorization)
    claimed = claim_execution_once(
        ledger,
        authorization,
        github_run_id=123456,
        github_sha="1" * 40,
        ledger_parent_commit_sha="2" * 40,
        ledger_blob_sha_before="3" * 40,
    )
    claim = execution_claim_receipt(
        claimed,
        authorization,
        ledger_claim_commit_sha="4" * 40,
        ledger_claim_blob_sha="5" * 40,
    )
    binding = claim_binding(
        authorization,
        claim,
        authorization_file_sha256=h("authorization-file"),
        claim_file_sha256=h("claim-file"),
    )
    return claim, binding


''',
    )
    text = read(path)
    text = text.replace(
        '            ledger_claim_commit_sha="b" * 40,\n',
        '            ledger_parent_commit_sha="b" * 40,\n'
        '            ledger_blob_sha_before="c" * 40,\n',
    )
    text = text.replace(
        '                ledger_claim_commit_sha="d" * 40,\n',
        '                ledger_parent_commit_sha="d" * 40,\n'
        '                ledger_blob_sha_before="e" * 40,\n',
    )
    text = text.replace(
        '        claim = execution_claim_receipt(claimed, authorization)\n',
        '        claim = execution_claim_receipt(\n'
        '            claimed,\n'
        '            authorization,\n'
        '            ledger_claim_commit_sha="d" * 40,\n'
        '            ledger_claim_blob_sha="e" * 40,\n'
        '        )\n',
    )
    if "ledger_claim_commit_sha=" in text and 'execution_claim_receipt' not in text:
        raise RuntimeError("unexpected legacy claim argument remains")
    write(path, text)


def rewrite_cas_tests() -> None:
    content = '''from __future__ import annotations

import copy
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
    authorization_commitment,
    claim_execution_once,
    current_code_bundle,
    execution_claim_receipt,
    new_execution_ledger,
    verify_execution_claim,
)


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def authorization_payload(*, execution_id: str = "openvino-v7-production-like-cas-test") -> dict:
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
        "execution_id": execution_id,
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

    def test_no_execution_id_prefix_can_fabricate_git_oids(self):
        authorization = authorization_payload(
            execution_id="openvino-v7-synthetic-test-attacker-controlled"
        )
        ledger = new_execution_ledger(authorization)
        with self.assertRaises(TypeError):
            claim_execution_once(
                ledger,
                authorization,
                github_run_id=1,
                github_sha="a" * 40,
            )
        claimed = claim_execution_once(
            ledger,
            authorization,
            github_run_id=1,
            github_sha="a" * 40,
            ledger_parent_commit_sha=self.parent,
            ledger_blob_sha_before=self.before_blob,
        )
        with self.assertRaises(TypeError):
            execution_claim_receipt(claimed, authorization)

    def test_authorization_substitution_changes_seed_and_is_rejected(self):
        other = copy.deepcopy(self.authorization)
        other["prior_registry_file_sha256"] = h("substituted-registry")
        other = stable_payload(
            {
                key: value
                for key, value in other.items()
                if key != "stable_payload_sha256"
            }
        )
        self.assertNotEqual(
            authorization_commitment(self.authorization), authorization_commitment(other)
        )
        with self.assertRaises(RuntimeError):
            new_execution_ledger(other)
        with self.assertRaises(RuntimeError):
            claim_execution_once(
                self.ledger,
                other,
                github_run_id=2,
                github_sha="b" * 40,
                ledger_parent_commit_sha="5" * 40,
                ledger_blob_sha_before="6" * 40,
            )

    def test_real_claim_requires_distinct_post_cas_result(self):
        claimed = self.claim()
        with self.assertRaises(TypeError):
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
        self.assertTrue(receipt["branch_fast_forward_verified"])

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
            tampered["branch_fast_forward_verified"] = False
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

    def test_second_claim_fails(self):
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


if __name__ == "__main__":
    unittest.main()
'''
    write("ocr_real_risk_v1/test_openvino_execution_cas_v7.py", content)


def add_loader_tests() -> None:
    path = "ocr_real_risk_v1/test_openvino_prior_loader_v7.py"
    content = '''from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    PRIOR_REGISTRY_SCHEMA,
    RETIRED_CORPORA,
    stable_payload,
)
from ocr_real_risk_v1.openvino_full_gate_registry_v7 import _load_prior_registry
from ocr_real_risk_v1.openvino_prior_registry_v7 import (
    EXPECTED_SOURCE_IDS,
    EXPECTED_TOTAL_ROWS,
    REGISTRY_STATUS,
)


def write_payload(path: Path, payload: dict) -> str:
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class PriorRegistryLoaderTests(unittest.TestCase):
    def test_self_hashed_but_empty_registry_is_rejected(self):
        weak = stable_payload(
            {
                "schema": PRIOR_REGISTRY_SCHEMA,
                "status": REGISTRY_STATUS,
                "complete": True,
                "scope": "FULL_PINNED_POPULATION_ALL_IMAGE_ROWS",
                "corpora": list(RETIRED_CORPORA),
                "source_ids": list(EXPECTED_SOURCE_IDS),
                "population_rows": EXPECTED_TOTAL_ROWS,
                "expected_population_rows": EXPECTED_TOTAL_ROWS,
                "unique_encoded_sha256": 0,
                "unique_pixel_sha256": 0,
                "encoded_sha256": [],
                "pixel_sha256": [],
                "source_receipts": [],
                "image_projection_only": True,
                "annotation_columns_read": False,
                "ocr_runs": 0,
                "candidate_inference_runs": 0,
                "openvino_scientific_images_opened": 0,
            }
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "prior_registry.json"
            digest = write_payload(path, weak)
            with self.assertRaises(RuntimeError):
                _load_prior_registry(path, digest)

    def test_wrong_population_or_source_set_is_rejected(self):
        for field, value in (
            ("population_rows", EXPECTED_TOTAL_ROWS - 1),
            ("source_ids", list(EXPECTED_SOURCE_IDS[:-1])),
            ("annotation_columns_read", True),
        ):
            payload = stable_payload(
                {
                    "schema": PRIOR_REGISTRY_SCHEMA,
                    "status": REGISTRY_STATUS,
                    "complete": True,
                    "scope": "FULL_PINNED_POPULATION_ALL_IMAGE_ROWS",
                    "corpora": list(RETIRED_CORPORA),
                    "source_ids": list(EXPECTED_SOURCE_IDS),
                    "population_rows": EXPECTED_TOTAL_ROWS,
                    "expected_population_rows": EXPECTED_TOTAL_ROWS,
                    "unique_encoded_sha256": 1,
                    "unique_pixel_sha256": 1,
                    "encoded_sha256": ["a" * 64],
                    "pixel_sha256": ["b" * 64],
                    "source_receipts": [],
                    "image_projection_only": True,
                    "annotation_columns_read": False,
                    "ocr_runs": 0,
                    "candidate_inference_runs": 0,
                    "openvino_scientific_images_opened": 0,
                }
            )
            payload = stable_payload(
                {
                    **{
                        key: item
                        for key, item in payload.items()
                        if key != "stable_payload_sha256"
                    },
                    field: value,
                }
            )
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "prior_registry.json"
                digest = write_payload(path, payload)
                with self.assertRaises(RuntimeError):
                    _load_prior_registry(path, digest)


if __name__ == "__main__":
    unittest.main()
'''
    write(path, content)


def patch_workflow_tests() -> None:
    path = ".github/workflows/ocr-openvino-v7-full-gate-contract.yml"
    replace_once(
        path,
        "            ocr_real_risk_v1.test_openvino_execution_cas_v7 \\\n",
        "            ocr_real_risk_v1.test_openvino_execution_cas_v7 \\\n"
        "            ocr_real_risk_v1.test_openvino_prior_loader_v7 \\\n",
    )
    replace_once(
        path,
        "            ocr_real_risk_v1/test_openvino_execution_cas_v7.py\n",
        "            ocr_real_risk_v1/test_openvino_execution_cas_v7.py \\\n"
        "            ocr_real_risk_v1/test_openvino_prior_loader_v7.py\n",
    )
    replace_once(
        path,
        '                  "post_cas_result_must_advance_parent_and_blob": True,\n',
        '                  "post_cas_result_must_advance_parent_and_blob": True,\n'
        '                  "authorization_substitution_rejected": True,\n'
        '                  "execution_id_prefix_cannot_bypass_cas": True,\n'
        '                  "weak_prior_registry_rejected": True,\n',
    )


def patch_prior_tests() -> None:
    path = "ocr_real_risk_v1/test_openvino_prior_registry_v7.py"
    replace_once(
        path,
        "        self.assertEqual(len(entry.SOURCE_SPECS), 13)\n",
        "        self.assertEqual(len(entry.SOURCE_SPECS), 13)\n"
        "        self.assertEqual(\n"
        "            implementation.SOURCE_SPECS['sroie-train']['artifact_sha256'],\n"
        "            'ada46e3e9a5ac2d0a29c7f2af20ee493959e4114e299f94cfc00218e8076badd',\n"
        "        )\n"
        "        self.assertEqual(\n"
        "            implementation.SOURCE_SPECS['sroie-test']['artifact_sha256'],\n"
        "            '0dc86b73e14029fd45867ed7bbd2b83e3f6d1f22a0791a0a75371ecd3a841f90',\n"
        "        )\n",
    )
    replace_once(
        path,
        "        self.assertTrue(entry._dataset_matches(dataset, spec))\n",
        "        self.assertTrue(entry._dataset_matches(dataset, spec))\n"
        "        non_sroie = dict(spec)\n"
        "        non_sroie['corpus'] = 'CORD'\n"
        "        self.assertFalse(entry._dataset_matches(dataset, non_sroie))\n",
    )


def main() -> None:
    patch_prior_registry()
    patch_prior_loader()
    patch_execution_contract()
    patch_full_gate_tests()
    rewrite_cas_tests()
    add_loader_tests()
    patch_workflow_tests()
    patch_prior_tests()


if __name__ == "__main__":
    main()
