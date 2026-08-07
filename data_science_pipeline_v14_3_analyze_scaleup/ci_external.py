from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid JWT shape")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def validate_oidc(token_path: Path, output: Path) -> None:
    token = token_path.read_text()
    claims = decode_payload(token)
    expected_ref = "refs/heads/agent/data-science-v14-3-analyze-scaleup-execution-v1"
    expected_workflow = "cristh99/notebooks/.github/workflows/data-science-v14-3-analyze-scaleup.yml@" + expected_ref
    checks = {
        "issuer": claims.get("iss") == "https://token.actions.githubusercontent.com",
        "audience": claims.get("aud") == "sigstore",
        "repository": claims.get("repository") == "cristh99/notebooks",
        "repository_id": claims.get("repository_id") == "616013328",
        "repository_owner_id": claims.get("repository_owner_id") == "87334928",
        "ref": claims.get("ref") == expected_ref,
        "sha": claims.get("sha") == os.environ["GITHUB_SHA"],
        "event": claims.get("event_name") in ("push", "workflow_dispatch"),
        "runner": claims.get("runner_environment") == "github-hosted",
        "workflow_ref": claims.get("workflow_ref") == expected_workflow,
        "subject": claims.get("sub") == "repo:cristh99/notebooks:ref:" + expected_ref,
    }
    if not all(checks.values()):
        raise RuntimeError({key: value for key, value in checks.items() if not value})
    safe = {
        "schema": "data-science-pipeline/github-oidc-safe-claims/1",
        "checks": checks,
        "claims": {key: claims.get(key) for key in (
            "iss", "aud", "sub", "repository", "repository_id", "repository_owner_id",
            "repository_visibility", "ref", "sha", "workflow_ref", "workflow_sha",
            "event_name", "runner_environment", "run_id", "run_attempt",
        )},
        "jwt_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "token_redacted": True,
    }
    output.write_bytes(canonical(safe))


def finalize(evidence: Path, runtime: Path, output: Path) -> None:
    result_path = runtime / "SCALEUP_RESULT.json"
    cohort_path = runtime / "SCALEUP_COHORT.jsonl"
    manifest_path = runtime / "SCALEUP_MANIFEST.json"
    source_path = runtime / "SOURCE_IDENTITY.json"
    quarantine_path = runtime / "QUARANTINE.jsonl"
    local_path = evidence / "local-receipt.json"
    oidc_path = evidence / "oidc-safe-claims.json"
    bundle_path = evidence / "scaleup-result.sigstore.json"
    verify_path = evidence / "verify.log"
    tests_path = evidence / "tests.log"

    result = json.loads(result_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    local = json.loads(local_path.read_text())
    oidc = json.loads(oidc_path.read_text())
    bundle = json.loads(bundle_path.read_text())
    entries = bundle.get("verificationMaterial", {}).get("tlogEntries", [])
    tests = tests_path.read_text()
    checks = {
        "terminal": result["terminal"] == "ANALYSIS_EXECUTION_VALIDATED",
        "reason": result["reason"] == "BOUNDED_PREREGISTERED_CANARY_SUFFICIENT",
        "minimum_cells": all(value >= 5 for value in result["selected_group_counts"].values()),
        "target_limit": all(value <= 20 for value in result["selected_group_counts"].values()),
        "hypothesis_executed": result["hypothesis_test_executed"] is True,
        "association_only": "association-only" in result["claim_boundary"],
        "negative_control": result["negative_control"]["promoted"] is False,
        "fdr_bounded": 0.0 <= result["bh_adjusted_p"] <= 1.0,
        "stage10_blocked": result["governance"]["stage10_unblocked"] is False,
        "production_unmodified": result["governance"]["production_modified"] is False,
        "zero_cost": result["governance"]["external_cost_usd"] == 0.0,
        "zero_scientific_credit": result["governance"]["scientific_promotion_credit"] == 0,
        "local_verdict": local["verdict"] == "PASS_STAGE09_PREREGISTERED_SCALEUP_LOCAL",
        "local_checks": all(local["checks"].values()),
        "oidc_checks": all(oidc["checks"].values()),
        "tests_50": "Ran 50 tests" in tests and "\nOK" in tests,
        "manifest_terminal": manifest["terminal"] == result["terminal"],
        "bundle_media_type": str(bundle.get("mediaType", "")).startswith("application/vnd.dev.sigstore.bundle.") and str(bundle.get("mediaType", "")).endswith("+json"),
        "transparency_entry": isinstance(entries, list) and len(entries) >= 1,
        "signature_verified": "Verified OK" in verify_path.read_text(),
    }
    if not all(checks.values()):
        raise RuntimeError({key: value for key, value in checks.items() if not value})
    receipt = {
        "schema": "data-science-pipeline/stage09-scaleup-external-receipt/1",
        "verdict": "PASS_STAGE09_PREREGISTERED_SCALEUP_EXTERNAL",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "github_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "github_run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "github_sha": os.environ["GITHUB_SHA"],
        "github_ref": os.environ["GITHUB_REF"],
        "checks": checks,
        "tests": "50/50 PASS",
        "source_identity_sha256": sha256(source_path),
        "source_archive_sha256": json.loads(source_path.read_text())["sha256"],
        "source_archive_bytes": json.loads(source_path.read_text())["bytes"],
        "cohort_sha256": sha256(cohort_path),
        "cohort_rows": manifest["selected_rows"],
        "selected_group_counts": result["selected_group_counts"],
        "result_sha256": sha256(result_path),
        "manifest_sha256": sha256(manifest_path),
        "quarantine_sha256": sha256(quarantine_path),
        "local_receipt_sha256": sha256(local_path),
        "oidc_safe_claims_sha256": sha256(oidc_path),
        "sigstore_bundle_sha256": sha256(bundle_path),
        "verify_log_sha256": sha256(verify_path),
        "terminal": result["terminal"],
        "reason": result["reason"],
        "stage10_canary_input_ready": True,
        "stage10_global_unblocked": False,
        "external_real_data_evaluations": 1,
        "external_cost_usd": 0.0,
        "production_modified": False,
        "scientific_promotion_credit": 0,
        "claim_boundary": "bounded association-only canary; no causality, wrongdoing, rankings, production readiness, or global Stage10 readiness",
        "next_gate": "independent replication on a separately pinned source version and governance review before any Stage10 work",
    }
    output.write_bytes(canonical(receipt))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-oidc")
    validate.add_argument("--token", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    finish = sub.add_parser("finalize")
    finish.add_argument("--evidence", type=Path, required=True)
    finish.add_argument("--runtime", type=Path, required=True)
    finish.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate-oidc":
        validate_oidc(args.token, args.output)
    else:
        finalize(args.evidence, args.runtime, args.output)


if __name__ == "__main__":
    main()
