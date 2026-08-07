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
    padding = "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment + padding))


def validate_oidc(token_path: Path, output: Path) -> None:
    token = token_path.read_text().strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise SystemExit("invalid JWT structure")
    claims = decode_segment(parts[1])
    expected_ref = f"refs/heads/{os.environ['EXPECTED_BRANCH']}"
    expected_sub = f"repo:{os.environ['EXPECTED_REPOSITORY']}:ref:{expected_ref}"
    audience = claims.get("aud")
    audience_ok = audience == os.environ["OIDC_AUDIENCE"] or (
        isinstance(audience, list) and os.environ["OIDC_AUDIENCE"] in audience
    )
    workflow_ref = str(claims.get("workflow_ref", ""))
    checks = {
        "issuer_exact": claims.get("iss") == os.environ["OIDC_ISSUER"],
        "audience_exact": audience_ok,
        "subject_exact": claims.get("sub") == expected_sub,
        "repository_exact": claims.get("repository") == os.environ["EXPECTED_REPOSITORY"],
        "repository_id_exact": str(claims.get("repository_id")) == os.environ["EXPECTED_REPOSITORY_ID"],
        "repository_owner_id_exact": str(claims.get("repository_owner_id")) == os.environ["EXPECTED_OWNER_ID"],
        "ref_exact": claims.get("ref") == expected_ref,
        "sha_exact": claims.get("sha") == os.environ["GITHUB_SHA"],
        "event_allowed": claims.get("event_name") in {"push", "workflow_dispatch"},
        "runner_environment_exact": claims.get("runner_environment") == "github-hosted",
        "workflow_ref_exact": workflow_ref == f"{os.environ['EXPECTED_REPOSITORY']}/{os.environ['EXPECTED_WORKFLOW_PATH']}@{expected_ref}",
    }
    if not all(checks.values()):
        raise SystemExit(checks)
    safe_claims = {
        key: claims.get(key)
        for key in [
            "iss", "aud", "sub", "repository", "repository_id", "repository_owner_id",
            "ref", "sha", "event_name", "runner_environment", "workflow_ref", "run_id", "run_attempt",
        ]
    }
    payload = {
        "schema": "data-science-pipeline/analyze-real-oidc-safe-claims/1",
        "checks": checks,
        "claims": safe_claims,
        "jwt_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "token_redacted": True,
    }
    output.write_bytes(canonical_bytes(payload))


def finalize(evidence: Path, output_path: Path) -> None:
    result_path = evidence / "analysis-result.json"
    contract_path = Path(os.environ["CONTRACT"])
    oidc_path = evidence / "oidc-safe-claims.json"
    bundle_path = evidence / "analyze-real.sigstore.json"
    verify_path = evidence / "verify.log"
    tests_path = evidence / "tests.log"
    artifact_meta_path = evidence / "semantic-artifact-metadata.json"

    result = json.loads(result_path.read_text())
    contract = json.loads(contract_path.read_text())
    oidc = json.loads(oidc_path.read_text())
    bundle = json.loads(bundle_path.read_text())
    artifact_meta = json.loads(artifact_meta_path.read_text())
    tests_text = tests_path.read_text()
    verify_text = verify_path.read_text()
    material = bundle.get("verificationMaterial", {})
    entries = material.get("tlogEntries", [])
    stats = result["statistical_outputs"]
    population = result["population"]
    readiness = result["readiness"]
    guards = result["guardrails"]

    checks = {
        "verdict_exact": result["verdict"] == "PASS_STAGE09_REAL_CANARY_NOT_EVALUABLE_MIN_CELL_SIZE",
        "terminal_exact": result["terminal_state"] == "ANALYSIS_NOT_EVALUABLE",
        "reason_exact": result["reason_code"] == "NOT_EVALUABLE_MIN_CELL_SIZE",
        "semantic_snapshot_hash_exact": result["input"]["semantic_snapshot_sha256"] == os.environ["SEMANTIC_SNAPSHOT_SHA256"],
        "semantic_artifact_id_exact": result["input"]["semantic_artifact_id"] == int(os.environ["SEMANTIC_ARTIFACT_ID"]),
        "semantic_artifact_digest_exact": artifact_meta.get("digest") == os.environ["SEMANTIC_ARTIFACT_DIGEST"],
        "two_semantic_rows": result["input"]["semantic_row_count"] == 2,
        "one_contract_row": population["eligible_contract_rows"] == 1,
        "payment_excluded": population["excluded_role_counts"] == {"PAYMENT": 1},
        "minimum_cell_n_five": population["minimum_cell_n"] == 5,
        "minimum_observed_below_five": population["minimum_observed_evaluable_cell_n"] < 5,
        "registered_analysis_not_executed": result["registered_analysis"]["executed"] is False,
        "all_statistical_outputs_null": all(value is None for value in stats.values()),
        "no_cross_role_aggregation": guards["cross_role_amount_aggregation_performed"] is False,
        "no_outcome_imputation": guards["low_competition_imputed"] is False,
        "no_raw_identity": guards["raw_identity_exported"] is False,
        "no_ranking": guards["ranking_emitted"] is False,
        "no_causal_claim": guards["causal_claim_emitted"] is False,
        "no_wrongdoing_label": guards["wrongdoing_label_emitted"] is False,
        "no_relationship_record": guards["relationship_record_included"] is False,
        "no_documentary_candidate": guards["documentary_candidate_included"] is False,
        "analysis_not_evaluable": readiness["analysis_evaluable"] is False,
        "stage10_input_blocked": readiness["stage10_canary_input_ready"] is False,
        "stage10_global_blocked": readiness["stage10_global_unblocked"] is False,
        "tests_36_pass": "Ran 36 tests" in tests_text and "OK" in tests_text,
        "oidc_all_checks": all(oidc["checks"].values()) and oidc["token_redacted"] is True,
        "bundle_media_type": str(bundle.get("mediaType", "")).startswith("application/vnd.dev.sigstore.bundle.") and str(bundle.get("mediaType", "")).endswith("+json"),
        "transparency_log_present": isinstance(entries, list) and len(entries) >= 1,
        "signature_verified": "Verified OK" in verify_text,
        "zero_cost": result["governance"]["external_cost_usd"] == 0.0,
        "production_unmodified": result["governance"]["production_modified"] is False,
        "scientific_credit_zero": result["governance"]["scientific_promotion_credit"] == 0,
        "merge_not_authorized": result["governance"]["merge_authorized"] is False,
        "contract_expected_terminal": contract["expected_terminal"]["reason_code"] == result["reason_code"],
    }
    if not all(checks.values()):
        raise SystemExit({key: value for key, value in checks.items() if not value})

    receipt = {
        "schema": "data-science-pipeline/analyze-real-min-cell-external-receipt/1",
        "verdict": "PASS_STAGE09_REAL_CANARY_NOT_EVALUABLE_MIN_CELL_SIZE_EXTERNAL",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "github_ref": os.environ["GITHUB_REF"],
        "github_sha": os.environ["GITHUB_SHA"],
        "github_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "github_run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "semantic_pr": 149,
        "analyze_reference_pr": 143,
        "semantic_artifact_id": int(os.environ["SEMANTIC_ARTIFACT_ID"]),
        "semantic_artifact_digest": os.environ["SEMANTIC_ARTIFACT_DIGEST"],
        "semantic_snapshot_sha256": os.environ["SEMANTIC_SNAPSHOT_SHA256"],
        "analysis_result_sha256": sha(result_path),
        "contract_sha256": sha(contract_path),
        "tests_log_sha256": sha(tests_path),
        "oidc_safe_claims_sha256": sha(oidc_path),
        "sigstore_bundle_sha256": sha(bundle_path),
        "verify_log_sha256": sha(verify_path),
        "checks": checks,
        "tests": "36/36 PASS",
        "input_rows": 2,
        "eligible_contract_rows": 1,
        "terminal_state": "ANALYSIS_NOT_EVALUABLE",
        "reason_code": "NOT_EVALUABLE_MIN_CELL_SIZE",
        "statistical_outputs_emitted": 0,
        "external_real_data_evaluations": 1,
        "stage10_canary_input_ready": False,
        "stage10_global_unblocked": False,
        "external_cost_usd": 0.0,
        "production_modified": False,
        "scientific_promotion_credit": 0,
        "next_gate": "preregistered_scale_up_with_at_least_five_evaluable_contract_events_in_each_registered_method_group",
    }
    output_path.write_bytes(canonical_bytes(receipt))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-oidc")
    validate.add_argument("--token", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
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
