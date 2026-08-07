from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
from pathlib import Path


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(segment: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def validate_oidc(token_path: Path, output: Path) -> None:
    token = token_path.read_text().strip()
    header, payload, _ = token.split(".")
    h, c, now = decode(header), decode(payload), int(time.time())
    repo = os.environ["EXPECTED_REPOSITORY"]
    branch = os.environ["EXPECTED_BRANCH"]
    expected_ref = f"refs/heads/{branch}"
    expected_workflow = f"{repo}/.github/workflows/data-science-v14-5-signed-exclusion-registry.yml@{expected_ref}"
    checks = {
        "alg_rs256": h.get("alg") == "RS256",
        "kid_present": bool(h.get("kid")),
        "issuer_exact": c.get("iss") == os.environ["OIDC_ISSUER"],
        "audience_exact": c.get("aud") == os.environ["OIDC_AUDIENCE"],
        "repository_exact": c.get("repository") == repo,
        "ref_exact": c.get("ref") == expected_ref,
        "sha_exact": c.get("sha") == os.environ["GITHUB_SHA"],
        "workflow_ref_exact": c.get("workflow_ref") == expected_workflow,
        "workflow_sha_exact": c.get("workflow_sha") == os.environ["GITHUB_SHA"],
        "event_allowed": c.get("event_name") in {"push", "workflow_dispatch"},
        "runner_github_hosted": c.get("runner_environment") == "github-hosted",
        "time_valid": int(c.get("nbf", 0)) <= now < int(c.get("exp", 0)),
        "subject_exact": c.get("sub") == f"repo:{repo}:ref:{expected_ref}",
    }
    if not all(checks.values()):
        raise SystemExit([key for key, value in checks.items() if not value])
    result = {
        "schema": "data-science-pipeline/stage09-exclusion-registry-oidc-safe-claims/1",
        "header": h,
        "claims": c,
        "checks": checks,
        "jwt_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "token_redacted": True,
        "registry_sha256": os.environ["REGISTRY_SHA256"],
    }
    output.write_bytes(canonical(result))


def finalize(evidence: Path, subject: Path, contract: Path, output: Path) -> None:
    local = json.loads((evidence / "local-result.json").read_text())
    oidc = json.loads((evidence / "oidc-safe-claims.json").read_text())
    registry = json.loads(subject.read_text())
    before = int((evidence / "registry-signing-preflight-epoch.txt").read_text().strip()) < int(os.environ["BEACON_NOT_BEFORE_EPOCH"])
    checks = {
        "tests_36_pass": local["verdict"] == "PASS_STAGE09_SIGNED_EXCLUSION_REGISTRY_SOFTWARE_ONLY",
        "local_checks_all_true": all(local["checks"].values()),
        "registry_hash_exact": sha(subject) == os.environ["REGISTRY_SHA256"],
        "registry_self_hash_exact": registry["self_hash_sha256"] == os.environ["REGISTRY_SELF_HASH"],
        "contract_hash_exact": sha(contract) == os.environ["CONTRACT_SHA256"],
        "entries_exact": local["entry_count"] == 8,
        "disclosed_candidates_exact": local["disclosed_selected_candidates_excluded"] == 26,
        "oidc_checks_all_true": all(oidc["checks"].values()),
        "oidc_token_redacted": oidc["token_redacted"] is True,
        "signed_content_present": (evidence / "exclusion-registry.sigstore.json").stat().st_size > 0,
        "cosign_verified_ok": "Verified OK" in (evidence / "verify.log").read_text(),
        "signed_before_beacon_threshold": before,
        "beacon_unconsumed": local["beacon_consumed"] is False,
        "cohort_unselected": local["cohort_selected"] is False,
        "outcome_unaccessed": local["outcome_accessed"] is False,
        "analysis_unexecuted": local["analysis_executed"] is False,
        "stage10_blocked": local["stage10_unblocked"] is False,
        "production_unmodified": local["production_modified"] is False,
        "cost_zero": local["external_cost_usd"] == 0.0,
    }
    if not all(checks.values()):
        raise SystemExit([key for key, value in checks.items() if not value])
    receipt = {
        "schema": "data-science-pipeline/stage09-exclusion-registry-external-receipt/1",
        "verdict": "PASS_STAGE09_SIGNED_EXCLUSION_REGISTRY_EXTERNAL",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "github_sha": os.environ["GITHUB_SHA"],
        "github_ref": os.environ["GITHUB_REF"],
        "github_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "github_run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "registry_sha256": sha(subject),
        "registry_self_hash_sha256": registry["self_hash_sha256"],
        "contract_sha256": sha(contract),
        "contamination_entries": 8,
        "disclosed_selected_candidates_excluded": 26,
        "tests": "36/36 PASS",
        "signed_before_beacon_threshold": before,
        "beacon_not_before_utc": "2026-08-08T00:00:00Z",
        "beacon_consumed": False,
        "cohort_selected": False,
        "outcome_accessed": False,
        "analysis_executed": False,
        "stage10_unblocked": False,
        "production_modified": False,
        "external_cost_usd": 0.0,
        "oidc_safe_claims_sha256": sha(evidence / "oidc-safe-claims.json"),
        "sigstore_bundle_sha256": sha(evidence / "exclusion-registry.sigstore.json"),
        "cosign_verify_log_sha256": sha(evidence / "verify.log"),
        "checks": checks,
        "next_gate": "signed_nist_beacon_pulse_at_or_after_2026_08_08T00_00_00Z",
    }
    receipt["self_hash_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    output.write_bytes(canonical(receipt))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    oidc = sub.add_parser("validate-oidc")
    oidc.add_argument("--token", type=Path, required=True)
    oidc.add_argument("--output", type=Path, required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--evidence", type=Path, required=True)
    final.add_argument("--subject", type=Path, required=True)
    final.add_argument("--contract", type=Path, required=True)
    final.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate-oidc":
        validate_oidc(args.token, args.output)
    else:
        finalize(args.evidence, args.subject, args.contract, args.output)

if __name__ == "__main__":
    main()
