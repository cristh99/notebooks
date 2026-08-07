from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any


EXPECTED_REPOSITORY = "cristh99/notebooks"
EXPECTED_REPOSITORY_ID = "616013328"
EXPECTED_OWNER_ID = "87334928"
EXPECTED_BRANCH = "agent/data-science-v14-2-stage09-real-min-cell-v1"
EXPECTED_WORKFLOW_PATH = ".github/workflows/data-science-v14-2-stage09-real-min-cell.yml"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_AUDIENCE = "sigstore"


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_segment(segment: str) -> dict[str, Any]:
    segment += "=" * (-len(segment) % 4)
    value = json.loads(base64.urlsafe_b64decode(segment.encode()))
    if not isinstance(value, dict):
        raise ValueError("JWT segment is not an object")
    return value


def validate_oidc(token_path: Path, output: Path) -> None:
    token = token_path.read_text()
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid JWT structure")
    claims = decode_segment(parts[1])
    expected_ref = f"refs/heads/{EXPECTED_BRANCH}"
    expected_workflow_ref = f"{EXPECTED_REPOSITORY}/{EXPECTED_WORKFLOW_PATH}@{expected_ref}"
    checks = {
        "issuer": claims.get("iss") == OIDC_ISSUER,
        "audience": claims.get("aud") == OIDC_AUDIENCE,
        "repository": claims.get("repository") == EXPECTED_REPOSITORY,
        "repository_id": str(claims.get("repository_id")) == EXPECTED_REPOSITORY_ID,
        "repository_owner_id": str(claims.get("repository_owner_id")) == EXPECTED_OWNER_ID,
        "ref": claims.get("ref") == expected_ref,
        "workflow_ref": claims.get("workflow_ref") == expected_workflow_ref,
        "sha": claims.get("sha") == os.environ.get("GITHUB_SHA"),
        "event_name": claims.get("event_name") in {"push", "workflow_dispatch"},
    }
    if not all(checks.values()):
        raise ValueError(f"OIDC claim checks failed: {checks}")
    safe = {
        "schema": "data-science-pipeline/github-oidc-safe-claims/1",
        "checks": checks,
        "issuer": claims.get("iss"),
        "audience": claims.get("aud"),
        "repository": claims.get("repository"),
        "repository_id": str(claims.get("repository_id")),
        "repository_owner_id": str(claims.get("repository_owner_id")),
        "ref": claims.get("ref"),
        "workflow_ref": claims.get("workflow_ref"),
        "sha": claims.get("sha"),
        "event_name": claims.get("event_name"),
    }
    output.write_bytes(canonical(safe))


def finalize(evidence: Path, result: Path, local_receipt: Path, output: Path) -> None:
    verify_log = (evidence / "cosign-verify.log").read_text()
    tests_log = (evidence / "tests.log").read_text()
    safe = json.loads((evidence / "oidc-safe-claims.json").read_text())
    local = json.loads(local_receipt.read_text())
    analysis = json.loads(result.read_text())
    bundle = evidence / "stage09-real.sigstore.json"
    checks = {
        "local_verdict": local.get("verdict") == "PASS_STAGE09_REAL_CANARY_FAIL_CLOSED_MINIMUM_CELL",
        "local_checks": all(local.get("checks", {}).values()),
        "tests_60_of_60": "Ran 60 tests" in tests_log and "\nOK" in tests_log,
        "oidc_safe_claims": all(safe.get("checks", {}).values()),
        "cosign_verified_ok": "Verified OK" in verify_log,
        "bundle_present": bundle.is_file() and bundle.stat().st_size > 0,
        "result_terminal": analysis.get("terminal_state") == "ANALYSIS_NOT_EVALUABLE",
        "minimum_cell_detail": analysis.get("terminal_detail") == "ANALYSIS_NOT_EVALUABLE_MINIMUM_CELL_SIZE",
        "inferential_execution_blocked": analysis.get("gates", {}).get("inferential_execution_allowed") is False,
        "inferential_outputs_zero": analysis.get("hypothesis_results", [{}])[0].get("inferential_outputs_emitted") == 0,
        "relationship_claims_zero": analysis.get("claim_boundary", {}).get("cross_source_relationship_assertions_emitted") == 0,
        "causal_wrongdoing_rankings_zero": (
            analysis.get("claim_boundary", {}).get("causal_claims_emitted") == 0
            and analysis.get("claim_boundary", {}).get("wrongdoing_labels_emitted") == 0
            and analysis.get("claim_boundary", {}).get("public_rankings_emitted") == 0
        ),
        "production_unmodified": analysis.get("governance", {}).get("production_modified") is False,
        "stage10_blocked": analysis.get("governance", {}).get("stage10_global_unblocked") is False,
    }
    if not all(checks.values()):
        raise ValueError(f"external checks failed: {checks}")
    receipt = {
        "schema": "data-science-pipeline/stage09-real-canary-external-receipt/1",
        "verdict": "PASS_STAGE09_REAL_CANARY_EXTERNAL_FAIL_CLOSED_MINIMUM_CELL",
        "checks": checks,
        "github": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "ref": os.environ.get("GITHUB_REF"),
            "sha": os.environ.get("GITHUB_SHA"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "event_name": os.environ.get("GITHUB_EVENT_NAME"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
        },
        "file_sha256": {
            "result": sha(result),
            "local_receipt": sha(local_receipt),
            "sigstore_bundle": sha(bundle),
            "cosign_verify_log": sha(evidence / "cosign-verify.log"),
            "oidc_safe_claims": sha(evidence / "oidc-safe-claims.json"),
            "tests_log": sha(evidence / "tests.log"),
        },
        "terminal_state": analysis["terminal_state"],
        "terminal_detail": analysis["terminal_detail"],
        "tests": "60/60 PASS",
        "external_real_data_evaluations": 1,
        "inferential_outputs_emitted": 0,
        "scientific_promotion_credit": 0,
        "external_cost_usd": 0.0,
        "production_modified": False,
        "mass_processing_authorized": False,
        "merge_authorized": False,
        "stage10_canary_input_ready": False,
        "stage10_global_unblocked": False,
        "claim_limit": local["claim_limit"],
    }
    receipt["receipt_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    output.write_bytes(canonical(receipt))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    oidc = sub.add_parser("validate-oidc")
    oidc.add_argument("--token", type=Path, required=True)
    oidc.add_argument("--output", type=Path, required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--evidence", type=Path, required=True)
    final.add_argument("--result", type=Path, required=True)
    final.add_argument("--local-receipt", type=Path, required=True)
    final.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate-oidc":
        validate_oidc(args.token, args.output)
    else:
        finalize(args.evidence, args.result, args.local_receipt, args.output)


if __name__ == "__main__":
    main()
