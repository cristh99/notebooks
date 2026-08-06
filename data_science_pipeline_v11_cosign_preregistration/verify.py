from __future__ import annotations

import argparse
import hashlib
import io
import json
import py_compile
import sys
import unittest
from pathlib import Path

from verify_static import canonical_bytes, validate_file

HERE = Path(__file__).resolve().parent
WORKFLOW = HERE.parent / ".github/workflows/data-science-v11-cosign-direct-oidc.yml"
FILES = {
    "preregistration": HERE / "PREREGISTRATION.json",
    "verifier": HERE / "verify_static.py",
    "tests": HERE / "test_static.py",
}
REQUIRED_WORKFLOW_TOKENS = {
    "id-token: write",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "--identity-token",
    " sign-blob",
    " verify-blob",
    "--certificate-identity-regexp",
    "--certificate-oidc-issuer",
    "--certificate-github-workflow-repository",
    "--certificate-github-workflow-sha",
    "--certificate-github-workflow-trigger",
    "c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74",
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_tests() -> tuple[int, list[str]]:
    suite = unittest.defaultTestLoader.discover(
        str(HERE),
        pattern="test_static.py",
        top_level_dir=str(HERE),
    )
    test_ids: list[str] = []

    def collect(node: unittest.TestSuite | unittest.TestCase) -> None:
        if isinstance(node, unittest.TestSuite):
            for item in node:
                collect(item)
        else:
            test_ids.append(node.id())

    collect(suite)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError(stream.getvalue())
    return result.testsRun, sorted(test_ids)


def verify(output: Path) -> dict[str, object]:
    freeze = json.loads((HERE / "FREEZE.json").read_text(encoding="utf-8"))
    require(
        freeze["schema"] == "data-science-pipeline/cosign-oidc-preregistration-freeze/1",
        "freeze schema mismatch",
    )

    checks = validate_file(FILES["preregistration"])
    require(all(checks.values()), "preregistration policy checks failed")

    expected_hashes = freeze["file_sha256"]
    actual_hashes = {name: sha256(path) for name, path in FILES.items()}
    require(actual_hashes == expected_hashes, "frozen source hash mismatch")

    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    missing_tokens = sorted(REQUIRED_WORKFLOW_TOKENS - {token for token in REQUIRED_WORKFLOW_TOKENS if token in workflow_text})
    require(not missing_tokens, f"workflow contract token missing: {missing_tokens}")
    require("attestations: write" not in workflow_text, "GitHub attestation API permission forbidden in direct-cosign path")
    require("secrets." not in workflow_text, "workflow must not depend on repository secrets")
    require("pull_request_target" not in workflow_text, "pull_request_target forbidden")

    tests_run, test_ids = run_tests()
    require(tests_run == freeze["expected_tests"], "test count mismatch")

    for path in (FILES["verifier"], FILES["tests"], HERE / "verify.py"):
        py_compile.compile(str(path), doraise=True)

    preregistration = json.loads(FILES["preregistration"].read_text(encoding="utf-8"))
    source = preregistration["source_selection"]
    controls = preregistration["execution_controls"]
    trust = preregistration["trust_contract"]
    receipt = {
        "schema": "data-science-pipeline/cosign-oidc-preregistration-local-receipt/1",
        "verdict": "PASS_COSIGN_OIDC_PREREGISTRATION_SOFTWARE_ONLY",
        "software_checks": {
            "preregistration_policy_pass": True,
            "frozen_source_hashes_exact": True,
            "workflow_contract_tokens_present": True,
            "workflow_secrets_absent": True,
            "github_attestation_api_permission_absent": True,
            "tests_pass": True,
            "compile_pass": True,
        },
        "preregistration_declarations": {
            "document_content_accessed_before_freeze": source["document_content_accessed_before_freeze"],
            "pdf_url_resolved_before_freeze": source["pdf_url_resolved_before_freeze"],
            "pdf_bytes_downloaded_before_freeze": source["pdf_bytes_downloaded_before_freeze"],
            "actual_external_evaluations": controls["actual_external_evaluations"],
            "stage08_unblocked": controls["stage08_unblocked"],
            "external_cost_usd": controls["external_cost_usd"],
            "production_modified": controls["production_modified"],
        },
        "trust_contract": {
            "mechanism": trust["mechanism"],
            "oidc_issuer": trust["oidc_issuer"],
            "oidc_audience": trust["oidc_audience"],
            "repository": trust["repository"],
            "allowed_events": trust["allowed_events"],
            "expected_head_branch": trust["expected_head_branch"],
            "expected_base_branch": trust["expected_base_branch"],
            "allowed_ref_patterns": trust["allowed_ref_patterns"],
            "workflow_path": trust["workflow_path"],
            "certificate_identity_regexp": trust["certificate_identity_regexp"],
            "cosign_version": trust["cosign_version"],
            "cosign_linux_amd64_sha256": trust["cosign_linux_amd64_sha256"],
        },
        "file_sha256": actual_hashes,
        "tests_expected": freeze["expected_tests"],
        "test_ids": test_ids,
        "base_v10_head_sha": freeze["base_v10_head_sha"],
        "sigstore_bundle_created": False,
        "fresh_external_document_still_required": True,
        "local_verification_external_cost_usd": 0.0,
        "production_modified_by_local_verifier": False,
        "scientific_promotion_credit": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "LOCAL_RESULT.json")
    args = parser.parse_args()
    receipt = verify(args.output)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
