"""Unified pre-source gate for the OpenVINO v7 scientific execution.

Every source-reading entry point calls this gate after authorization validation
and before any dataset access.  It proves the exact runtime lock is active and
that the irreversible terminal-ledger implementation was frozen in advance.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .core import sha256_file
from .openvino_runtime_lock_v7 import verify_runtime_lock
from .openvino_terminal_ledger_v7 import terminal_source_sha256

RUNTIME_ROOT_ENV = "OPENVINO_RUNTIME_LOCK_ROOT"


def preexecution_source_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def verify_preexecution_gate(authorization: Mapping[str, Any]) -> dict[str, Any]:
    """Fail before source access unless runtime and terminal code are frozen."""
    if authorization.get("preexecution_gate_source_sha256") != preexecution_source_sha256():
        raise RuntimeError("preexecution gate source differs from authorization")
    if authorization.get("terminal_ledger_source_sha256") != terminal_source_sha256():
        raise RuntimeError("terminal ledger source differs from authorization")
    root_value = os.environ.get(RUNTIME_ROOT_ENV)
    if not root_value:
        raise RuntimeError(f"{RUNTIME_ROOT_ENV} is required")
    runtime = verify_runtime_lock(Path(root_value), authorization)
    return {
        "preexecution_gate_source_sha256": preexecution_source_sha256(),
        "terminal_ledger_source_sha256": terminal_source_sha256(),
        "runtime": runtime,
        "source_access_authorized": True,
        "speed_claim_authorized": False,
        "post_outcome_retry_authorized": False,
    }
