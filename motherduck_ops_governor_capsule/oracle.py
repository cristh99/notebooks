from __future__ import annotations

from collections.abc import Mapping
from typing import Any


LEASE_KEYS = frozenset(
    {
        "updated_within_6h",
        "run_active",
        "external_job_active",
        "watermark_changing",
        "declared_active",
    }
)

ONE_SHOT_MARKERS = frozenset(
    {
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
    }
)


def _count(case: Mapping[str, Any], field: str) -> int:
    value = case.get(field, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _true(case: Mapping[str, Any], field: str) -> bool:
    return bool(case.get(field, False))


def decide(case: Mapping[str, Any]) -> tuple[str, str]:
    """Independent finite oracle for recommendation and terminal only."""

    if not isinstance(case, Mapping):
        raise TypeError("case must be a mapping")

    hard_rejections = (
        (not _true(case, "authorized"), "BLOCKED", "REJECTED"),
        (not _true(case, "reversible"), "BLOCKED", "REJECTED"),
        (not _true(case, "receipt_preserved"), "BLOCKED", "REJECTED"),
    )
    for condition, recommendation, terminal in hard_rejections:
        if condition:
            return recommendation, terminal

    if any(_true(case, key) for key in LEASE_KEYS):
        return "KEEP_ACTIVE", "PASS"

    if _count(case, "same_failure_count") >= 3:
        return "RETIRE_SCHEDULE", "PASS"

    if _true(case, "external_terminal") and _count(case, "stable_observations") >= 2:
        return "RETIRE_SCHEDULE", "PASS"

    if str(case.get("superseded_by", "")).strip():
        return "RETIRE_SCHEDULE", "PASS"

    purpose_tokens = str(case.get("purpose", "")).lower()
    recurring_one_shot = _true(case, "scheduled") and any(
        marker in purpose_tokens for marker in ONE_SHOT_MARKERS
    )
    if recurring_one_shot:
        return "ON_DEMAND_ONLY", "PASS"

    noop_count = _count(case, "identical_noop_count")
    if noop_count >= 12:
        return "RETIRE_SCHEDULE", "PASS"
    if noop_count >= 3:
        return "BACKOFF", "PASS"

    runtime = _count(case, "p95_runtime_seconds")
    interval = _count(case, "interval_seconds")
    schedule_is_too_fast = (
        _true(case, "scheduled")
        and interval > 0
        and interval < max(300, 2 * runtime)
    )
    if schedule_is_too_fast:
        return "BACKOFF", "PASS"

    if _true(case, "repeated_status_questions"):
        return "BUILD_ANALYTIC_ASSET", "PASS"

    if _true(case, "material_delta"):
        return "NO_CHANGE", "PASS"

    return "BLOCKED", "UNKNOWN"
