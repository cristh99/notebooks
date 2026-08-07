from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


LEASE_FIELDS = (
    "updated_within_6h",
    "run_active",
    "external_job_active",
    "watermark_changing",
    "declared_active",
)

ONE_SHOT_TOKENS = (
    "once",
    "diagnostic",
    "verify",
    "verification",
    "profile",
    "inspect",
    "readonly",
    "read-only",
    "builder",
    "repair",
    "probe",
    "audit",
    "canary",
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def semantic_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bool(case: Mapping[str, Any], key: str) -> bool:
    return bool(case.get(key, False))


def _int(case: Mapping[str, Any], key: str) -> int:
    value = case.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    if value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def _selected(
    case: Mapping[str, Any],
    recommendation: str,
    terminal: str,
    reason: str,
    reversal_condition: str,
) -> dict[str, Any]:
    packet = {
        "case_id": str(case.get("case_id", "")),
        "recommendation": recommendation,
        "terminal": terminal,
        "reason": reason,
        "reversal_condition": reversal_condition,
    }
    packet["digest"] = semantic_digest(packet)
    return packet


def evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a frozen MotherDuck operations case without external effects."""

    if not isinstance(case, Mapping):
        raise TypeError("case must be a mapping")

    if not _bool(case, "authorized"):
        return _selected(
            case,
            "BLOCKED",
            "REJECTED",
            "The proposed operation lacks explicit authority.",
            "Provide valid per-run authority for the proposed external effect.",
        )

    if not _bool(case, "reversible"):
        return _selected(
            case,
            "BLOCKED",
            "REJECTED",
            "The proposed operation is irreversible under the declared plan.",
            "Provide a reversible plan or explicit consent for irreversibility.",
        )

    if not _bool(case, "receipt_preserved"):
        return _selected(
            case,
            "BLOCKED",
            "REJECTED",
            "The only execution receipt would not be preserved.",
            "Persist the receipt and provenance outside the mutable operation.",
        )

    active_leases = sorted(field for field in LEASE_FIELDS if _bool(case, field))
    if active_leases:
        return _selected(
            case,
            "KEEP_ACTIVE",
            "PASS",
            "Protected lease fields are active: " + ",".join(active_leases),
            "Re-evaluate after all lease fields are false in two consecutive observations.",
        )

    same_failure_count = _int(case, "same_failure_count")
    if same_failure_count >= 3:
        return _selected(
            case,
            "RETIRE_SCHEDULE",
            "PASS",
            "The same deterministic failure repeated at least three times.",
            "Reactivate only after an isolated repair passes the frozen regression case.",
        )

    external_terminal = _bool(case, "external_terminal")
    stable_observations = _int(case, "stable_observations")
    if external_terminal and stable_observations >= 2:
        return _selected(
            case,
            "RETIRE_SCHEDULE",
            "PASS",
            "The external resource is terminal and unchanged across two observations.",
            "Create a new bounded monitor only if a new external resource starts.",
        )

    if str(case.get("superseded_by", "")).strip():
        return _selected(
            case,
            "RETIRE_SCHEDULE",
            "PASS",
            "A declared successor already owns the same operational function.",
            "Reconsider only if the successor is withdrawn or fails its authority contract.",
        )

    purpose = str(case.get("purpose", "")).lower()
    if _bool(case, "scheduled") and any(token in purpose for token in ONE_SHOT_TOKENS):
        return _selected(
            case,
            "ON_DEMAND_ONLY",
            "PASS",
            "A one-shot or diagnostic purpose must not retain a recurring schedule.",
            "A documented durable purpose with idempotence and a stopping rule would reverse this.",
        )

    noop_count = _int(case, "identical_noop_count")
    if noop_count >= 12:
        return _selected(
            case,
            "RETIRE_SCHEDULE",
            "PASS",
            "Twelve identical NOOP observations show no decision-changing delta.",
            "A new input fingerprint or watermark delta would justify an on-demand run.",
        )
    if noop_count >= 3:
        return _selected(
            case,
            "BACKOFF",
            "PASS",
            "Three identical NOOP observations require at least a threefold interval increase.",
            "Material delta in the next observation would retain or shorten the interval.",
        )

    p95_runtime_seconds = _int(case, "p95_runtime_seconds")
    interval_seconds = _int(case, "interval_seconds")
    minimum_interval = max(300, 2 * p95_runtime_seconds)
    if _bool(case, "scheduled") and interval_seconds and interval_seconds < minimum_interval:
        return _selected(
            case,
            "BACKOFF",
            "PASS",
            f"Schedule interval {interval_seconds}s is below the safe minimum {minimum_interval}s.",
            "A lower measured p95 with mutual exclusion would permit a shorter interval.",
        )

    if _bool(case, "repeated_status_questions"):
        return _selected(
            case,
            "BUILD_ANALYTIC_ASSET",
            "PASS",
            "Repeated questions can be answered from existing state without another polling pipeline.",
            "A required datum absent from all current tables and system metadata would reverse this.",
        )

    if _bool(case, "material_delta"):
        return _selected(
            case,
            "NO_CHANGE",
            "PASS",
            "The operation is producing material delta and no protected lease is currently active.",
            "Two stable observations without delta would reopen backoff or retirement.",
        )

    return _selected(
        case,
        "BLOCKED",
        "UNKNOWN",
        "Available observations do not separate keep, backoff, repair, or retirement.",
        "Obtain one additional admissible watermark, run-state, or error-fingerprint observation.",
    )
