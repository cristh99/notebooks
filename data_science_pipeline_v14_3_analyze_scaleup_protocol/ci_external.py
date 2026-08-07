from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_segment(segment: str) -> dict[str, Any]:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def validate_oidc(token_path: Path, output_path: Path) -> None:
    token = token_path.read_text().strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise SystemExit("invalid JWT")
    claims = decode_segment(parts[1])
    ref = f"refs/heads/{os.environ['EXPECTED_BRANCH']}"
    aud = claims.get("aud")
    checks = {
        "issuer_exact": claims.get("iss") == os.environ["OIDC_ISSUER"],
        "audience_exact": aud == os.environ["OIDC_AUDIENCE"] or (isinstance(aud, list) and os.environ["OIDC_AUDIENCE"] in aud),
        "subject_exact": claims.get("sub") == f"repo:{os.environ['EXPECTED_REPOSITORY']}:ref:{ref}",
        "repository_exact": claims.get("repository") == os.environ["EXPECTED_REPOSITORY"],
        "repository_id_exact": str(claims.get("repository_id")) == os.environ["EXPECTED_REPOSITORY_ID"],
        "owner_id_exact": str(claims.get("repository_owner_id")) == os.environ["EXPECTED_OWNER_ID"],
        "ref_exact": claims.get("ref") == ref,
        "sha_exact": claims.get("sha") == os.environ["GITHUB_SHA"],
        "event_allowed": claims.get("event_name") in {"push", "workflow_dispatch"},
        "runner_hosted": claims.get("runner_environment") == "github-hosted",
        "workflow_ref_exact": claims.get("workflow_ref") == f"{os.environ['EXPECTED_REPOSITORY']}/{os.environ['EXPECTED_WORKFLOW_PATH']}@{ref}",
    }
    if not all(checks.values()):
        raise SystemExit(checks)
    safe = {key: claims.get(key) for key in ["iss", "aud", "sub", "repository", "repository_id", "repository_owner_id", "ref", "sha", "event_name", "runner_environment", "workflow_ref", "run_id", "run_attempt"]}
    output_path.write_bytes(canonical_bytes({
        "schema": "data-science-pipeline/analyze-scaleup-oidc-safe-claims/1",
        "checks": checks,
        "claims": safe,
        "jwt_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "token_redacted": True,
    }))


def finalize(evidence: Path, output_path: Path) -> None:
    protocol_path = Path(os.environ["PROTOCOL"])
    manifest_path = evidence / "synthetic-cohort-manifest.json"
    tests_path = evidence / "tests.log"
    oidc_path = evidence / "oidc-safe-claims.json"
    bundle_path = evidence / "protocol.sigstore.json"
    verify_path = evidence / "verify.log"
    protocol = json.loads(protocol_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    oidc = json.loads(oidc_path.read_text())
    bundle = json.loads(bundle_path.read_text())
    tests = tests_path.read_text()
    entries = bundle.get("verificationMaterial", {}).get("tlogEntries", [])
    checks = {
        "protocol_schema": protocol["schema"] == "data-science-pipeline/analyze-scaleup-protocol/1",
        "upstream_canary_exact": protocol["upstream"]["analyze_canary_pr"] == 150,
        "hypothesis_unchanged": protocol["analysis_plan"]["hypothesis_id"] == "H09-001",
        "minimum_cell_five": protocol["analysis_plan"]["minimum_evaluable_cell_n"] == 5,
        "groups_exact": protocol["sampling"]["groups"] == ["DIRECT", "OPEN"],
        "primary_ten": protocol["sampling"]["primary_per_group"] == 10,
        "reserve_ten": protocol["sampling"]["reserve_per_group"] == 10,
        "maximum_forty": protocol["governance"]["maximum_selected_events"] == 40,
        "outcome_blind": protocol["discovery_blinding"]["outcome_accessed"] is False and protocol["discovery_blinding"]["selection_uses_outcome"] is False,
        "explicit_bid_only": protocol["outcome_reveal"]["bid_count_requirement"] == "explicit_nonnegative_integer_field",
        "empty_tenderers_not_zero": protocol["outcome_reveal"]["empty_tenderers_is_zero"] is False,
        "synthetic_terminal": manifest["terminal_state"] == "COHORT_FROZEN_BLIND",
        "synthetic_selected_forty": manifest["sampling"]["selected_event_count"] == 40,
        "manifest_blind": all(value is False for value in manifest["blinding"].values()),
        "analysis_not_allowed": manifest["readiness"]["analysis_allowed"] is False,
        "stage10_blocked": manifest["readiness"]["stage10_unblocked"] is False,
        "tests_48_pass": "Ran 48 tests" in tests and "OK" in tests,
        "oidc_checks": all(oidc["checks"].values()) and oidc["token_redacted"] is True,
        "bundle_media_type": str(bundle.get("mediaType", "")).startswith("application/vnd.dev.sigstore.bundle.") and str(bundle.get("mediaType", "")).endswith("+json"),
        "transparency_present": isinstance(entries, list) and len(entries) >= 1,
        "signature_verified": "Verified OK" in verify_path.read_text(),
        "zero_cost": protocol["governance"]["external_cost_usd"] == 0.0,
        "production_unmodified": protocol["governance"]["production_modified"] is False,
        "real_cohort_not_claimed": manifest["input"]["candidate_rows"] == 40 and protocol["discovery_blinding"]["outcome_accessed"] is False,
    }
    if not all(checks.values()):
        raise SystemExit({key: value for key, value in checks.items() if not value})
    receipt = {
        "schema": "data-science-pipeline/analyze-scaleup-protocol-external-receipt/1",
        "verdict": "PASS_STAGE09_SCALEUP_PROTOCOL_FROZEN_EXTERNAL",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "github_ref": os.environ["GITHUB_REF"],
        "github_sha": os.environ["GITHUB_SHA"],
        "github_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "github_run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "protocol_sha256": sha(protocol_path),
        "synthetic_manifest_sha256": sha(manifest_path),
        "tests_log_sha256": sha(tests_path),
        "oidc_safe_claims_sha256": sha(oidc_path),
        "sigstore_bundle_sha256": sha(bundle_path),
        "verify_log_sha256": sha(verify_path),
        "checks": checks,
        "tests": "48/48 PASS",
        "real_cohort_selected": False,
        "outcome_accessed": False,
        "analysis_executed": False,
        "stage10_unblocked": False,
        "external_cost_usd": 0.0,
        "production_modified": False,
        "scientific_promotion_credit": 0,
        "next_gate": "blind_read_only_candidate_inventory_then_signed_cohort_freeze",
    }
    output_path.write_bytes(canonical_bytes(receipt))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    oidc = sub.add_parser("validate-oidc")
    oidc.add_argument("--token", type=Path, required=True)
    oidc.add_argument("--output", type=Path, required=True)
    finish = sub.add_parser("finalize")
    finish.add_argument("--evidence", type=Path, required=True)
    finish.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate-oidc":
        validate_oidc(args.token, args.output)
    else:
        finalize(args.evidence, args.output)


if __name__ == "__main__":
    main()
