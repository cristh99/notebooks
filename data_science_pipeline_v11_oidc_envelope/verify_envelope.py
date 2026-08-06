from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENVELOPE_PATH = HERE / "ENVELOPE.json"
SCHEMA = "data-science-pipeline/oidc-preregistration-envelope/1"
REPO = "cristh99/notebooks"
REPO_ID = "616013328"
OWNER_ID = "87334928"
BASE_BRANCH = "agent/data-science-v11-envelope-bootstrap-base"
HEAD_BRANCH = "agent/data-science-v11-oidc-envelope"
WORKFLOW_PATH = ".github/workflows/data-science-v11-oidc-envelope.yml"
ISSUER = "https://token.actions.githubusercontent.com"
AUDIENCE = "sigstore"
ORIGINAL_COMMIT = "53e172b88095ea771912964e957c23f9446c3660"
ORIGINAL_BLOB = "73fc2696b943634b172c014b42c698ac72b3dd8e"
ORIGINAL_PATH = "data_science_pipeline_v11_cosign_preregistration/PREREGISTRATION.json"
COSIGN_SHA = "c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74"
CERT_RE = (
    r"^https://github\.com/cristh99/notebooks/\.github/workflows/"
    r"data-science-v11-oidc-envelope\.yml@"
    r"(refs/heads/agent/data-science-v11-envelope-bootstrap-base|"
    r"refs/heads/agent/data-science-v11-oidc-envelope|refs/pull/[0-9]+/merge)$"
)
SUBJECTS = {
    "repo:cristh99/notebooks:pull_request",
    "repo:cristh99@87334928/notebooks@616013328:pull_request",
}
SECRET_KEY = re.compile(
    r"(^|[_-])(secret|password|private[_-]?key|credential|api[_-]?key|access[_-]?token|auth[_-]?token)($|[_-])",
    re.I,
)
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def walk(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(not SECRET_KEY.search(str(key)), f"credential-like key at {path}.{key}")
            walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, f"{path}[{index}]")


def load_envelope() -> dict[str, object]:
    raw = ENVELOPE_PATH.read_bytes()
    payload = json.loads(raw)
    require(raw == canonical_bytes(payload), "envelope is not canonical JSON")
    validate_envelope(payload)
    return payload


def validate_envelope(payload: dict[str, object]) -> None:
    require(payload.get("schema") == SCHEMA, "schema mismatch")
    walk(payload)
    original = payload.get("original_preregistration")
    require(isinstance(original, dict), "original missing")
    require(original.get("repository") == REPO, "repository mismatch")
    require(original.get("branch") == "agent/data-science-v11-cosign-direct-oidc", "original branch mismatch")
    require(original.get("commit_sha") == ORIGINAL_COMMIT, "original commit mismatch")
    require(original.get("git_blob_sha") == ORIGINAL_BLOB, "original blob mismatch")
    require(original.get("path") == ORIGINAL_PATH, "original path mismatch")
    for field in ("source_document_content_opened", "source_pdf_bytes_downloaded", "source_pdf_url_resolved"):
        require(original.get(field) is False, f"{field} must be false")

    trust = payload.get("trust_contract")
    require(isinstance(trust, dict), "trust missing")
    require(trust.get("mechanism") == "github_actions_oidc_sigstore_cosign_keyless", "mechanism mismatch")
    require(trust.get("repository") == REPO, "trust repository mismatch")
    require(trust.get("repository_id") == REPO_ID, "repository id mismatch")
    require(trust.get("repository_owner_id") == OWNER_ID, "owner id mismatch")
    require(trust.get("repository_visibility") == "public", "visibility mismatch")
    require(trust.get("expected_base_branch") == BASE_BRANCH, "base mismatch")
    require(trust.get("expected_head_branch") == HEAD_BRANCH, "head mismatch")
    require(trust.get("workflow_path") == WORKFLOW_PATH, "workflow path mismatch")
    require(trust.get("oidc_issuer") == ISSUER, "issuer mismatch")
    require(trust.get("oidc_audience") == AUDIENCE, "audience mismatch")
    require(set(trust.get("allowed_oidc_subjects", [])) == SUBJECTS, "subject set mismatch")
    require(trust.get("allowed_certificate_identity_regexp") == CERT_RE, "certificate regexp mismatch")
    require(trust.get("cosign_version") == "3.0.6", "cosign version mismatch")
    require(trust.get("cosign_linux_amd64_sha256") == COSIGN_SHA, "cosign hash mismatch")
    for field in ("github_hosted_runner_required", "sigstore_bundle_required", "transparency_log_inclusion_required"):
        require(trust.get(field) is True, f"{field} must be true")

    controls = payload.get("execution_controls")
    require(isinstance(controls, dict), "controls missing")
    require(controls.get("actual_external_document_evaluations") == 0, "external evaluation already occurred")
    require(controls.get("external_cost_usd") == 0.0, "cost must be zero")
    for field in ("mass_processing_authorized", "merge_authorized", "paid_compute_used", "post_result_retuning_permitted", "production_modified", "stage08_unblocked"):
        require(controls.get(field) is False, f"{field} must be false")

    boundary = payload.get("claim_boundary")
    require(isinstance(boundary, dict), "claim boundary missing")
    require("truth_of_original_preregistration_declarations" in boundary.get("does_not_establish", []), "truth boundary missing")
    require("corruption" in boundary.get("does_not_establish", []), "corruption boundary missing")
    require("exact_original_preregistration_git_blob" in boundary.get("establishes_after_verified_signature", []), "blob scope missing")


def decode_jwt(token: str) -> tuple[dict[str, object], dict[str, object]]:
    parts = token.split(".")
    require(len(parts) == 3, "token is not JWT")
    def decode(part: str) -> dict[str, object]:
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return decode(parts[0]), decode(parts[1])


def validate_oidc(token_path: Path, event_path: Path, output: Path, github_env: Path) -> None:
    envelope = load_envelope()
    token = token_path.read_text()
    header, claims = decode_jwt(token)
    event = json.loads(event_path.read_text())
    pr = event.get("pull_request", {})
    head_sha = str(pr.get("head", {}).get("sha", ""))
    base_sha = str(pr.get("base", {}).get("sha", ""))
    merge_sha = os.environ["GITHUB_SHA"]
    ref = str(claims.get("ref", ""))
    base_ref = f"refs/heads/{BASE_BRANCH}"
    head_ref = f"refs/heads/{HEAD_BRANCH}"
    merge_ref = ref if re.fullmatch(r"refs/pull/[0-9]+/merge", ref) else ""
    allowed_workflow_refs = {
        f"{REPO}/{WORKFLOW_PATH}@{base_ref}",
        f"{REPO}/{WORKFLOW_PATH}@{head_ref}",
    }
    if merge_ref:
        allowed_workflow_refs.add(f"{REPO}/{WORKFLOW_PATH}@{merge_ref}")
    audience = claims.get("aud")
    audience_ok = AUDIENCE in audience if isinstance(audience, list) else audience == AUDIENCE
    now = int(time.time())
    checks = {
        "alg_rs256": header.get("alg") == "RS256",
        "kid_present": bool(header.get("kid")),
        "issuer_exact": claims.get("iss") == ISSUER,
        "audience_exact": audience_ok,
        "subject_exact": claims.get("sub") in SUBJECTS,
        "repository_exact": claims.get("repository") == REPO,
        "repository_id_exact": str(claims.get("repository_id")) == REPO_ID,
        "owner_id_exact": str(claims.get("repository_owner_id")) == OWNER_ID,
        "visibility_public": claims.get("repository_visibility") == "public",
        "event_pull_request": claims.get("event_name") == "pull_request",
        "head_exact": claims.get("head_ref") == HEAD_BRANCH,
        "base_exact": claims.get("base_ref") == BASE_BRANCH,
        "merge_ref_exact": bool(merge_ref),
        "sha_exact": claims.get("sha") == merge_sha,
        "workflow_ref_allowed": claims.get("workflow_ref") in allowed_workflow_refs,
        "workflow_sha_allowed": claims.get("workflow_sha") in {head_sha, base_sha, merge_sha},
        "runner_github_hosted": claims.get("runner_environment") == "github-hosted",
        "jti_present": bool(claims.get("jti")),
        "time_valid": int(claims.get("nbf", 0)) <= now < int(claims.get("exp", 0)) and int(claims.get("iat", 0)) <= now,
        "pr_shas_present": bool(head_sha and base_sha and SHA40.fullmatch(head_sha) and SHA40.fullmatch(base_sha)),
    }
    require(all(checks.values()), json.dumps(checks, sort_keys=True))
    safe = {
        "schema": "data-science-pipeline/github-oidc-safe-claims/2",
        "header": {"alg": header.get("alg"), "kid": header.get("kid"), "typ": header.get("typ")},
        "claims": {key: claims.get(key) for key in (
            "iss", "aud", "sub", "repository", "repository_id", "repository_owner_id",
            "repository_visibility", "event_name", "head_ref", "base_ref", "ref", "sha",
            "workflow_ref", "workflow_sha", "runner_environment", "run_id", "run_number",
            "run_attempt", "actor", "actor_id", "jti", "iat", "nbf", "exp")},
        "checks": checks,
        "jwt_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "token_redacted": True,
        "envelope_sha256": sha256(ENVELOPE_PATH),
    }
    output.write_bytes(canonical_bytes(safe))
    with github_env.open("a", encoding="utf-8") as handle:
        handle.write(f"OIDC_WORKFLOW_SHA={claims['workflow_sha']}\n")
        handle.write(f"OIDC_WORKFLOW_REF={claims['workflow_ref']}\n")


def static_receipt(output: Path) -> None:
    envelope = load_envelope()
    receipt = {
        "schema": "data-science-pipeline/oidc-preregistration-envelope-local-receipt/1",
        "verdict": "PASS_OIDC_ENVELOPE_SOFTWARE_ONLY",
        "envelope_sha256": sha256(ENVELOPE_PATH),
        "original_git_blob_sha": ORIGINAL_BLOB,
        "tests_expected": 14,
        "external_cost_usd": 0.0,
        "production_modified": False,
        "stage08_unblocked": False,
        "signature_created": False,
        "claim_boundary": envelope["claim_boundary"],
    }
    output.write_bytes(canonical_bytes(receipt))


def finalize(bundle: Path, verify_output: Path, claims_path: Path, local_receipt: Path, original_path: Path, output: Path) -> None:
    envelope = load_envelope()
    bundle_data = json.loads(bundle.read_text())
    material = bundle_data.get("verificationMaterial", {})
    tlog = material.get("tlogEntries", [])
    content = bundle_data.get("messageSignature") or bundle_data.get("dsseEnvelope")
    checks = {
        "sigstore_media_type": str(bundle_data.get("mediaType", "")).startswith("application/vnd.dev.sigstore.bundle+json"),
        "verification_material_present": bool(material),
        "transparency_log_entry_present": isinstance(tlog, list) and len(tlog) >= 1,
        "signed_content_present": bool(content),
        "cosign_verify_output_present": verify_output.stat().st_size > 0,
    }
    require(all(checks.values()), json.dumps(checks, sort_keys=True))
    receipt = {
        "schema": "data-science-pipeline/oidc-preregistration-envelope-external-receipt/1",
        "verdict": "PASS_OIDC_ENVELOPE_SIGNATURE",
        "github_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "github_run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "github_sha": os.environ["GITHUB_SHA"],
        "github_ref": os.environ["GITHUB_REF"],
        "repository": os.environ["GITHUB_REPOSITORY"],
        "oidc_workflow_ref": os.environ["OIDC_WORKFLOW_REF"],
        "oidc_workflow_sha": os.environ["OIDC_WORKFLOW_SHA"],
        "envelope_sha256": sha256(ENVELOPE_PATH),
        "original_preregistration_sha256": sha256(original_path),
        "original_preregistration_git_blob_sha": ORIGINAL_BLOB,
        "local_receipt_sha256": sha256(local_receipt),
        "oidc_safe_claims_sha256": sha256(claims_path),
        "sigstore_bundle_sha256": sha256(bundle),
        "cosign_verify_output_sha256": sha256(verify_output),
        "cryptographic_checks": checks,
        "signature_scope": envelope["claim_boundary"],
        "external_document_evaluations": 0,
        "external_cost_usd": 0.0,
        "production_modified": False,
        "stage08_unblocked": False,
        "next_gate": "one_bounded_fresh_full_document_evaluation",
    }
    output.write_bytes(canonical_bytes(receipt))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    static = sub.add_parser("static")
    static.add_argument("--output", type=Path, required=True)
    oidc = sub.add_parser("oidc")
    oidc.add_argument("--token", type=Path, required=True)
    oidc.add_argument("--event", type=Path, required=True)
    oidc.add_argument("--output", type=Path, required=True)
    oidc.add_argument("--github-env", type=Path, required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--bundle", type=Path, required=True)
    final.add_argument("--verify-output", type=Path, required=True)
    final.add_argument("--claims", type=Path, required=True)
    final.add_argument("--local-receipt", type=Path, required=True)
    final.add_argument("--original", type=Path, required=True)
    final.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "static":
        static_receipt(args.output)
    elif args.command == "oidc":
        validate_oidc(args.token, args.event, args.output, args.github_env)
    else:
        finalize(args.bundle, args.verify_output, args.claims, args.local_receipt, args.original, args.output)


if __name__ == "__main__":
    main()
