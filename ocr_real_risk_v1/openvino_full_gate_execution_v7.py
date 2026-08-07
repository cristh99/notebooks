"""Atomic-execution, code-bundle, and one-shot claim contracts for OpenVINO v7."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .core import sha256_file
from .openvino_full_gate_contract_v7 import (
    AUTHORIZATION_SCHEMA,
    CANDIDATE_STABLE_PAYLOAD_SHA256,
    MODEL_ARTIFACT_ID,
    MODEL_ZIP_SHA256,
    PARTITION_COUNT,
    SCIENTIFIC_MANIFEST_SHA256,
    SOURCE_OBJECT_SHA256,
    _is_sha256,
    _read_json,
    stable_payload,
    verify_execution_authorization as verify_base_authorization,
    verify_stable_payload,
)

MANIFEST_ARTIFACT_ID = 8983596179
MANIFEST_ARTIFACT_SHA256 = (
    "fda92bb57ba4088481b6cedded374366b6c6635951942cd3e4f42688292fe182"
)
EXECUTION_LEDGER_SCHEMA = "eaat.openvino_v7_execution_ledger/1"
EXECUTION_CLAIM_SCHEMA = "eaat.openvino_v7_execution_claim/1"
LEDGER_APPROVED = "APPROVED_NOT_CLAIMED"
LEDGER_CLAIMED = "CLAIMED_FULL_EXTERNAL_GATE_ONCE"
LEDGER_TERMINAL = "TERMINAL_FULL_EXTERNAL_GATE"

CRITICAL_CODE_PATHS = (
    "ocr_real_risk_v1/core.py",
    "ocr_real_risk_v1/exact_bounds.py",
    "ocr_real_risk_v1/isolated_crop.py",
    "ocr_real_risk_v1/pixel_digit_alignment.py",
    "ocr_real_risk_v1/sroie_natural_holdout.py",
    "ocr_real_risk_v1/numeric_digit_forest.py",
    "ocr_real_risk_v1/cord_source_seal.py",
    "ocr_real_risk_v1/numeric_digit_forest_deterministic.py",
    "ocr_real_risk_v1/cord_natural_holdout.py",
    "ocr_real_risk_v1/cord_consensus_detector_v4.py",
    "ocr_real_risk_v1/cord_detector_crops_v4.py",
    "ocr_real_risk_v1/textocr_adapter_v6.py",
    "ocr_real_risk_v1/numeric_consensus_policy_v7.py",
    "ocr_real_risk_v1/openvino_smoke_v7.py",
    "ocr_real_risk_v1/openvino_full_gate_contract_v7.py",
    "ocr_real_risk_v1/openvino_full_gate_execution_v7.py",
    "ocr_real_risk_v1/openvino_full_gate_prepare_v7.py",
    "ocr_real_risk_v1/openvino_full_gate_registry_v7.py",
    "ocr_real_risk_v1/openvino_full_gate_runner_v7.py",
    "ocr_real_risk_v1/openvino_full_gate_aggregate_v7.py",
    "ocr_real_risk_v1/openvino_full_gate_v7.py",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def current_code_bundle(root: Path | None = None) -> dict[str, str]:
    base = repository_root() if root is None else Path(root)
    result: dict[str, str] = {}
    for relative in CRITICAL_CODE_PATHS:
        path = base / relative
        if not path.is_file():
            raise RuntimeError(f"critical execution file is missing: {relative}")
        result[relative] = sha256_file(path)
    return result


def _valid_code_bundle(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == set(CRITICAL_CODE_PATHS)
        and all(_is_sha256(item) for item in value.values())
    )


def verify_bound_execution_authorization(
    path: Path,
    expected_file_sha256: str,
    required_scope: str,
) -> dict[str, Any]:
    payload = verify_base_authorization(path, expected_file_sha256, required_scope)
    if payload.get("schema") != AUTHORIZATION_SCHEMA:
        raise RuntimeError("unexpected authorization schema")
    if (
        payload.get("manifest_artifact_id") != MANIFEST_ARTIFACT_ID
        or payload.get("manifest_artifact_sha256") != MANIFEST_ARTIFACT_SHA256
        or payload.get("model_artifact_id") != MODEL_ARTIFACT_ID
        or payload.get("model_artifact_sha256") != MODEL_ZIP_SHA256
        or payload.get("partition_count") != PARTITION_COUNT
        or payload.get("runner_image") != "ubuntu-24.04"
        or payload.get("python_major_minor") != "3.11"
        or payload.get("tesseract_version") != "5.3.4"
        or not _is_sha256(payload.get("prior_registry_file_sha256"))
        or not _is_sha256(payload.get("prior_registry_stable_payload_sha256"))
        or not _is_sha256(payload.get("execution_ledger_initial_stable_payload_sha256"))
        or not isinstance(payload.get("execution_ledger_branch"), str)
        or not isinstance(payload.get("execution_ledger_path"), str)
        or not _valid_code_bundle(payload.get("code_bundle"))
    ):
        raise RuntimeError("authorization lacks frozen execution bindings")
    if dict(payload["code_bundle"]) != current_code_bundle():
        raise RuntimeError("authorization code bundle does not match checked-out executor")
    if (
        payload.get("candidate_stable_payload_sha256")
        != CANDIDATE_STABLE_PAYLOAD_SHA256
        or payload.get("scientific_manifest_sha256")
        != SCIENTIFIC_MANIFEST_SHA256
        or payload.get("source_object_sha256") != SOURCE_OBJECT_SHA256
    ):
        raise RuntimeError("authorization scientific identity drift")
    if new_execution_ledger(payload)["stable_payload_sha256"] != payload[
        "execution_ledger_initial_stable_payload_sha256"
    ]:
        raise RuntimeError("authorization does not bind its initial execution ledger")
    return payload


def _ledger_fields(authorization: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": EXECUTION_LEDGER_SCHEMA,
        "status": LEDGER_APPROVED,
        "execution_id": authorization["execution_id"],
        "authorization_nonce_sha256": authorization[
            "authorization_nonce_sha256"
        ],
        "candidate_stable_payload_sha256": CANDIDATE_STABLE_PAYLOAD_SHA256,
        "scientific_manifest_sha256": SCIENTIFIC_MANIFEST_SHA256,
        "source_object_sha256": SOURCE_OBJECT_SHA256,
        "code_bundle": dict(authorization["code_bundle"]),
        "claim_count": 0,
        "terminal": None,
    }


def new_execution_ledger(authorization: Mapping[str, Any]) -> dict[str, Any]:
    """Build the non-circular ledger seed later pinned by authorization."""
    required = (
        "execution_id",
        "authorization_nonce_sha256",
        "code_bundle",
    )
    if any(key not in authorization for key in required):
        raise RuntimeError("authorization fields are insufficient for ledger seed")
    ledger = stable_payload(_ledger_fields(authorization))
    expected = authorization.get("execution_ledger_initial_stable_payload_sha256")
    if expected is not None and expected != ledger["stable_payload_sha256"]:
        raise RuntimeError("execution ledger seed differs from authorization")
    return ledger


def claim_execution_once(
    ledger: Mapping[str, Any],
    authorization: Mapping[str, Any],
    *,
    github_run_id: int,
    github_sha: str,
    ledger_claim_commit_sha: str,
) -> dict[str, Any]:
    """Pure transition used by an atomic GitHub compare-and-swap ledger update."""
    if not verify_stable_payload(ledger):
        raise RuntimeError("execution ledger stable replay failed")
    if (
        ledger.get("schema") != EXECUTION_LEDGER_SCHEMA
        or ledger.get("status") != LEDGER_APPROVED
        or ledger.get("claim_count") != 0
        or ledger.get("terminal") is not None
        or ledger.get("stable_payload_sha256")
        != authorization.get("execution_ledger_initial_stable_payload_sha256")
        or ledger.get("execution_id") != authorization.get("execution_id")
        or ledger.get("authorization_nonce_sha256")
        != authorization.get("authorization_nonce_sha256")
        or ledger.get("code_bundle") != authorization.get("code_bundle")
    ):
        raise RuntimeError("execution authorization is already consumed or mismatched")
    if (
        not isinstance(github_run_id, int)
        or github_run_id <= 0
        or not isinstance(github_sha, str)
        or len(github_sha) != 40
        or not isinstance(ledger_claim_commit_sha, str)
        or len(ledger_claim_commit_sha) != 40
    ):
        raise RuntimeError("invalid GitHub execution claim identity")
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
                "ledger_claim_commit_sha": ledger_claim_commit_sha,
                "previous_ledger_stable_payload_sha256": ledger[
                    "stable_payload_sha256"
                ],
            },
        }
    )


def execution_claim_receipt(
    claimed_ledger: Mapping[str, Any], authorization: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        not verify_stable_payload(claimed_ledger)
        or claimed_ledger.get("status") != LEDGER_CLAIMED
        or claimed_ledger.get("claim_count") != 1
    ):
        raise RuntimeError("claimed ledger is invalid")
    claim = claimed_ledger.get("claim")
    if not isinstance(claim, Mapping):
        raise RuntimeError("claimed ledger lacks claim identity")
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
            "initial_ledger_stable_payload_sha256": authorization[
                "execution_ledger_initial_stable_payload_sha256"
            ],
            "claimed_ledger_stable_payload_sha256": claimed_ledger[
                "stable_payload_sha256"
            ],
            "github_run_id": claim["github_run_id"],
            "github_sha": claim["github_sha"],
            "ledger_claim_commit_sha": claim["ledger_claim_commit_sha"],
            "code_bundle": dict(authorization["code_bundle"]),
            "consumed_once": True,
        }
    )


def verify_execution_claim(
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
        or not verify_stable_payload(payload)
        or payload.get("execution_id") != authorization.get("execution_id")
        or payload.get("authorization_stable_payload_sha256")
        != authorization.get("stable_payload_sha256")
        or payload.get("authorization_nonce_sha256")
        != authorization.get("authorization_nonce_sha256")
        or payload.get("initial_ledger_stable_payload_sha256")
        != authorization.get("execution_ledger_initial_stable_payload_sha256")
        or payload.get("code_bundle") != authorization.get("code_bundle")
        or not _is_sha256(payload.get("claimed_ledger_stable_payload_sha256"))
        or not isinstance(payload.get("github_run_id"), int)
        or payload.get("github_run_id") <= 0
        or not isinstance(payload.get("github_sha"), str)
        or len(payload["github_sha"]) != 40
        or not isinstance(payload.get("ledger_claim_commit_sha"), str)
        or len(payload["ledger_claim_commit_sha"]) != 40
    ):
        raise RuntimeError("execution claim contract failed")
    return payload


def claim_binding(
    authorization: Mapping[str, Any],
    claim: Mapping[str, Any],
    *,
    authorization_file_sha256: str,
    claim_file_sha256: str,
) -> dict[str, Any]:
    return {
        "execution_id": authorization["execution_id"],
        "authorization_nonce_sha256": authorization[
            "authorization_nonce_sha256"
        ],
        "authorization_stable_payload_sha256": authorization[
            "stable_payload_sha256"
        ],
        "authorization_file_sha256": authorization_file_sha256,
        "execution_claim_stable_payload_sha256": claim[
            "stable_payload_sha256"
        ],
        "execution_claim_file_sha256": claim_file_sha256,
        "claimed_ledger_stable_payload_sha256": claim[
            "claimed_ledger_stable_payload_sha256"
        ],
        "ledger_claim_commit_sha": claim["ledger_claim_commit_sha"],
        "github_run_id": claim["github_run_id"],
        "github_sha": claim["github_sha"],
    }
