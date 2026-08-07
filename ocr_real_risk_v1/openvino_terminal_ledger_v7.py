"""One-shot terminal transition for the OpenVINO v7 scientific ledger.

A claimed execution may become terminal exactly once and only from a complete,
hash-bound aggregate.  The transition preserves PASS, FAIL, or ABSTAIN; it can
never authorize retuning, retries, production changes, or a second execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .core import sha256_file
from .openvino_full_gate_contract_v7 import (
    ABSTAIN_DEDUP_OR_INTEGRITY,
    AGGREGATE_SCHEMA,
    FAIL_FULL_EXTERNAL_GATE,
    PASS_FULL_EXTERNAL_GATE,
    _is_sha256,
    stable_payload,
    verify_stable_payload,
)
from .openvino_full_gate_execution_v7 import (
    CAS_STRATEGY,
    EXECUTION_CLAIM_SCHEMA,
    EXECUTION_LEDGER_SCHEMA,
    LEDGER_CLAIMED,
    LEDGER_TERMINAL,
    authorization_commitment,
    execution_claim_receipt,
)

TERMINAL_RECEIPT_SCHEMA = "eaat.openvino_v7_execution_terminal_receipt/1"
TERMINAL_VERDICTS = frozenset(
    {PASS_FULL_EXTERNAL_GATE, FAIL_FULL_EXTERNAL_GATE, ABSTAIN_DEDUP_OR_INTEGRITY}
)


def terminal_source_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def _git_oid(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 40 and all(character in "0123456789abcdef" for character in text)


def _verify_authorization(authorization: Mapping[str, Any]) -> None:
    if authorization.get("terminal_ledger_source_sha256") != terminal_source_sha256():
        raise RuntimeError("terminal ledger source differs from authorization")
    if authorization.get("post_outcome_retry_authorized") is not False:
        raise RuntimeError("authorization permits a forbidden post-outcome retry")
    if authorization.get("retuning_authorized") is not False:
        raise RuntimeError("authorization permits forbidden retuning")
    if authorization.get("run_once") is not True:
        raise RuntimeError("authorization is not one-shot")


def _verify_claim(
    claimed_ledger: Mapping[str, Any],
    authorization: Mapping[str, Any],
    execution_claim: Mapping[str, Any],
) -> None:
    if (
        claimed_ledger.get("schema") != EXECUTION_LEDGER_SCHEMA
        or claimed_ledger.get("status") != LEDGER_CLAIMED
        or claimed_ledger.get("claim_count") != 1
        or claimed_ledger.get("terminal") is not None
        or not verify_stable_payload(claimed_ledger)
    ):
        raise RuntimeError("ledger is not in the unique claimed state")
    if (
        execution_claim.get("schema") != EXECUTION_CLAIM_SCHEMA
        or execution_claim.get("status") != LEDGER_CLAIMED
        or execution_claim.get("consumed_once") is not True
        or not verify_stable_payload(execution_claim)
    ):
        raise RuntimeError("execution claim receipt is invalid")
    expected = execution_claim_receipt(
        claimed_ledger,
        authorization,
        ledger_claim_commit_sha=str(execution_claim.get("ledger_claim_commit_sha") or ""),
        ledger_claim_blob_sha=str(execution_claim.get("ledger_claim_blob_sha") or ""),
    )
    if dict(execution_claim) != expected:
        raise RuntimeError("execution claim is not bound to the claimed ledger")


def _verify_aggregate(aggregate: Mapping[str, Any]) -> str:
    verdict = str(aggregate.get("scientific_verdict") or aggregate.get("status") or "")
    if (
        aggregate.get("schema") != AGGREGATE_SCHEMA
        or verdict not in TERMINAL_VERDICTS
        or aggregate.get("status") != verdict
        or not verify_stable_payload(aggregate)
        or aggregate.get("automatic_production_change") is not False
        or aggregate.get("retuning_authorized") is not False
    ):
        raise RuntimeError("aggregate is not a valid terminal scientific result")
    integrity = aggregate.get("integrity")
    execution = aggregate.get("execution")
    if not isinstance(integrity, Mapping) or not isinstance(execution, Mapping):
        raise RuntimeError("aggregate lacks integrity/execution evidence")
    if verdict in {PASS_FULL_EXTERNAL_GATE, FAIL_FULL_EXTERNAL_GATE} and (
        integrity.get("pass") is not True
        or int(execution.get("partition_count", 0)) != 12
        or int(execution.get("selected", 0)) <= 0
    ):
        raise RuntimeError("quality verdict lacks complete twelve-partition execution")
    if verdict == ABSTAIN_DEDUP_OR_INTEGRITY and integrity.get("pass") is not False:
        raise RuntimeError("ABSTAIN does not identify an integrity failure")
    return verdict


def terminalize_execution_once(
    claimed_ledger: Mapping[str, Any],
    authorization: Mapping[str, Any],
    execution_claim: Mapping[str, Any],
    aggregate: Mapping[str, Any],
    *,
    aggregate_artifact_id: int,
    aggregate_artifact_sha256: str,
    aggregate_file_sha256: str,
    github_run_id: int,
    github_sha: str,
    ledger_parent_commit_sha: str,
    ledger_blob_sha_before: str,
) -> dict[str, Any]:
    """Create the pre-CAS terminal ledger transition exactly once."""
    _verify_authorization(authorization)
    _verify_claim(claimed_ledger, authorization, execution_claim)
    verdict = _verify_aggregate(aggregate)
    if (
        not isinstance(aggregate_artifact_id, int)
        or aggregate_artifact_id <= 0
        or not _is_sha256(aggregate_artifact_sha256)
        or not _is_sha256(aggregate_file_sha256)
        or not isinstance(github_run_id, int)
        or github_run_id != execution_claim.get("github_run_id")
        or github_sha != execution_claim.get("github_sha")
        or not _git_oid(github_sha)
        or ledger_parent_commit_sha != execution_claim.get("ledger_claim_commit_sha")
        or ledger_blob_sha_before != execution_claim.get("ledger_claim_blob_sha")
        or not _git_oid(ledger_parent_commit_sha)
        or not _git_oid(ledger_blob_sha_before)
    ):
        raise RuntimeError("terminal CAS or aggregate artifact identity drift")
    return stable_payload(
        {
            **{
                key: value
                for key, value in claimed_ledger.items()
                if key != "stable_payload_sha256"
            },
            "status": LEDGER_TERMINAL,
            "terminal_count": 1,
            "terminal": {
                "scientific_verdict": verdict,
                "aggregate_stable_payload_sha256": aggregate[
                    "stable_payload_sha256"
                ],
                "aggregate_artifact_id": aggregate_artifact_id,
                "aggregate_artifact_sha256": aggregate_artifact_sha256,
                "aggregate_file_sha256": aggregate_file_sha256,
                "github_run_id": github_run_id,
                "github_sha": github_sha,
                "cas_strategy": CAS_STRATEGY,
                "ledger_parent_commit_sha": ledger_parent_commit_sha,
                "ledger_blob_sha_before": ledger_blob_sha_before,
                "previous_ledger_stable_payload_sha256": claimed_ledger[
                    "stable_payload_sha256"
                ],
                "retuning_authorized": False,
                "post_outcome_retry_authorized": False,
                "automatic_production_change": False,
            },
        }
    )


def terminal_execution_receipt(
    terminal_ledger: Mapping[str, Any],
    authorization: Mapping[str, Any],
    execution_claim: Mapping[str, Any],
    aggregate: Mapping[str, Any],
    *,
    ledger_terminal_commit_sha: str,
    ledger_terminal_blob_sha: str,
) -> dict[str, Any]:
    """Bind the verified post-CAS commit/blob to the terminal transition."""
    if (
        terminal_ledger.get("schema") != EXECUTION_LEDGER_SCHEMA
        or terminal_ledger.get("status") != LEDGER_TERMINAL
        or terminal_ledger.get("terminal_count") != 1
        or not verify_stable_payload(terminal_ledger)
    ):
        raise RuntimeError("terminal ledger is invalid")
    terminal = terminal_ledger.get("terminal")
    if not isinstance(terminal, Mapping):
        raise RuntimeError("terminal ledger lacks terminal evidence")
    claimed = {
        **{
            key: value
            for key, value in terminal_ledger.items()
            if key not in {"stable_payload_sha256", "terminal_count"}
        },
        "status": LEDGER_CLAIMED,
        "terminal": None,
    }
    claimed = stable_payload(
        {key: value for key, value in claimed.items() if key != "stable_payload_sha256"}
    )
    expected = terminalize_execution_once(
        claimed,
        authorization,
        execution_claim,
        aggregate,
        aggregate_artifact_id=int(terminal["aggregate_artifact_id"]),
        aggregate_artifact_sha256=str(terminal["aggregate_artifact_sha256"]),
        aggregate_file_sha256=str(terminal["aggregate_file_sha256"]),
        github_run_id=int(terminal["github_run_id"]),
        github_sha=str(terminal["github_sha"]),
        ledger_parent_commit_sha=str(terminal["ledger_parent_commit_sha"]),
        ledger_blob_sha_before=str(terminal["ledger_blob_sha_before"]),
    )
    if dict(terminal_ledger) != expected:
        raise RuntimeError("terminal ledger is not the authorized transition")
    if (
        not _git_oid(ledger_terminal_commit_sha)
        or not _git_oid(ledger_terminal_blob_sha)
        or ledger_terminal_commit_sha == terminal["ledger_parent_commit_sha"]
        or ledger_terminal_blob_sha == terminal["ledger_blob_sha_before"]
    ):
        raise RuntimeError("terminal post-CAS Git identity did not advance")
    return stable_payload(
        {
            "schema": TERMINAL_RECEIPT_SCHEMA,
            "status": LEDGER_TERMINAL,
            "execution_id": authorization["execution_id"],
            "authorization_stable_payload_sha256": authorization[
                "stable_payload_sha256"
            ],
            "authorization_commitment_sha256": authorization_commitment(
                authorization
            ),
            "execution_claim_stable_payload_sha256": execution_claim[
                "stable_payload_sha256"
            ],
            "claimed_ledger_stable_payload_sha256": terminal[
                "previous_ledger_stable_payload_sha256"
            ],
            "terminal_ledger_stable_payload_sha256": terminal_ledger[
                "stable_payload_sha256"
            ],
            "scientific_verdict": terminal["scientific_verdict"],
            "aggregate_stable_payload_sha256": terminal[
                "aggregate_stable_payload_sha256"
            ],
            "aggregate_artifact_id": terminal["aggregate_artifact_id"],
            "aggregate_artifact_sha256": terminal["aggregate_artifact_sha256"],
            "aggregate_file_sha256": terminal["aggregate_file_sha256"],
            "github_run_id": terminal["github_run_id"],
            "github_sha": terminal["github_sha"],
            "cas_strategy": terminal["cas_strategy"],
            "ledger_parent_commit_sha": terminal["ledger_parent_commit_sha"],
            "ledger_blob_sha_before": terminal["ledger_blob_sha_before"],
            "ledger_terminal_commit_sha": ledger_terminal_commit_sha,
            "ledger_terminal_blob_sha": ledger_terminal_blob_sha,
            "branch_fast_forward_verified": True,
            "commit_parent_verified": True,
            "blob_content_verified": True,
            "terminal_once": True,
            "retuning_authorized": False,
            "post_outcome_retry_authorized": False,
            "automatic_production_change": False,
        }
    )


def verify_terminal_receipt(
    receipt: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        receipt.get("schema") != TERMINAL_RECEIPT_SCHEMA
        or receipt.get("status") != LEDGER_TERMINAL
        or receipt.get("terminal_once") is not True
        or receipt.get("scientific_verdict") not in TERMINAL_VERDICTS
        or receipt.get("authorization_stable_payload_sha256")
        != authorization.get("stable_payload_sha256")
        or receipt.get("authorization_commitment_sha256")
        != authorization_commitment(authorization)
        or not _is_sha256(receipt.get("execution_claim_stable_payload_sha256"))
        or not _is_sha256(receipt.get("claimed_ledger_stable_payload_sha256"))
        or not _is_sha256(receipt.get("terminal_ledger_stable_payload_sha256"))
        or not _is_sha256(receipt.get("aggregate_stable_payload_sha256"))
        or not _is_sha256(receipt.get("aggregate_artifact_sha256"))
        or not _is_sha256(receipt.get("aggregate_file_sha256"))
        or not _git_oid(receipt.get("ledger_parent_commit_sha"))
        or not _git_oid(receipt.get("ledger_blob_sha_before"))
        or not _git_oid(receipt.get("ledger_terminal_commit_sha"))
        or not _git_oid(receipt.get("ledger_terminal_blob_sha"))
        or receipt.get("ledger_terminal_commit_sha")
        == receipt.get("ledger_parent_commit_sha")
        or receipt.get("ledger_terminal_blob_sha")
        == receipt.get("ledger_blob_sha_before")
        or receipt.get("branch_fast_forward_verified") is not True
        or receipt.get("commit_parent_verified") is not True
        or receipt.get("blob_content_verified") is not True
        or receipt.get("retuning_authorized") is not False
        or receipt.get("post_outcome_retry_authorized") is not False
        or receipt.get("automatic_production_change") is not False
        or not verify_stable_payload(receipt)
    ):
        raise RuntimeError("terminal execution receipt contract failed")
    return dict(receipt)
