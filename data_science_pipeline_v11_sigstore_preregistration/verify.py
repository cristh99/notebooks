from __future__ import annotations

import argparse
import hashlib
import io
import json
import py_compile
import sys
import unittest
from pathlib import Path

from verify_preregistration import canonical_bytes, validate_file

HERE = Path(__file__).resolve().parent
FILES = {
    "preregistration": HERE / "PREREGISTRATION.json",
    "predicate": HERE / "PREDICATE.json",
    "verifier": HERE / "verify_preregistration.py",
    "tests": HERE / "test_preregistration.py",
    "workflow": HERE.parent / ".github/workflows/data-science-v11-sigstore-preregistration.yml",
}
PREDICATE_TYPE = "https://github.com/cristh99/notebooks/attestations/data-science-preregistration/v1"
EXPECTED_ATTESTATION_ESTABLISHES = {
    "subject_digest",
    "signer_workflow_identity",
    "source_repository_ref_and_digest",
    "preregistration_record_present_at_attested_commit",
}
EXPECTED_ATTESTATION_DOES_NOT_ESTABLISH = {
    "predicate_truth_without_trusted_workflow_review",
    "actual_precommit_document_nonaccess",
    "actual_external_evaluation_count_before_commit",
    "actual_cost_before_commit",
    "document_authenticity",
    "resolver_accuracy",
    "ocr_quality",
    "beneficial_ownership",
    "payment",
    "legality",
    "intent",
    "corruption",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_tests() -> tuple[int, list[str]]:
    suite = unittest.defaultTestLoader.discover(
        str(HERE),
        pattern="test_preregistration.py",
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
    require(freeze["schema"] == "data-science-pipeline/sigstore-preregistration-freeze/1", "freeze schema")
    checks = validate_file(FILES["preregistration"])
    require(all(checks.values()), "preregistration checks failed")

    expected_hashes = freeze["file_sha256"]
    actual_hashes = {name: sha256(path) for name, path in FILES.items()}
    require(actual_hashes == expected_hashes, "frozen file hash mismatch")

    predicate = json.loads(FILES["predicate"].read_text(encoding="utf-8"))
    require(FILES["predicate"].read_bytes() == canonical_bytes(predicate), "predicate not canonical")
    require(predicate["predicate_type"] == PREDICATE_TYPE, "predicate type mismatch")
    require(
        set(predicate["claim_boundary"]["attestation_establishes"])
        == EXPECTED_ATTESTATION_ESTABLISHES,
        "attestation establishes boundary mismatch",
    )
    require(
        set(predicate["claim_boundary"]["attestation_does_not_establish"])
        == EXPECTED_ATTESTATION_DOES_NOT_ESTABLISH,
        "attestation limitation boundary mismatch",
    )
    require(predicate["subject"]["sha256"] == actual_hashes["preregistration"], "predicate subject mismatch")
    require(
        predicate["implementation"]["preregistration_verifier_sha256"] == actual_hashes["verifier"],
        "predicate verifier mismatch",
    )
    require(
        predicate["implementation"]["preregistration_tests_sha256"] == actual_hashes["tests"],
        "predicate tests mismatch",
    )
    require(
        predicate["implementation"]["actions_attest_commit_sha"]
        == freeze["actions"]["attest_commit_sha"],
        "attest action pin mismatch",
    )
    require(
        predicate["implementation"]["workflow_sha256"] == actual_hashes["workflow"],
        "predicate workflow mismatch",
    )

    tests_run, test_ids = run_tests()
    require(tests_run == freeze["expected_tests"], "test count mismatch")
    for path in (FILES["verifier"], FILES["tests"], HERE / "verify.py"):
        py_compile.compile(str(path), doraise=True)

    preregistration = json.loads(FILES["preregistration"].read_text(encoding="utf-8"))
    source = preregistration["source_selection"]
    controls = preregistration["execution_controls"]
    receipt = {
        "schema": "data-science-pipeline/sigstore-preregistration-local-receipt/2",
        "verdict": "PASS_PREREGISTRATION_RECORD_SOFTWARE_ONLY",
        "software_checks": {
            "preregistration_policy_pass": True,
            "file_hashes_exact": True,
            "predicate_bound_to_subject": True,
            "predicate_claim_boundary_honest": True,
            "action_pin_exact": True,
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
        "file_sha256": actual_hashes,
        "predicate_type": PREDICATE_TYPE,
        "tests_expected": freeze["expected_tests"],
        "test_ids": test_ids,
        "base_v10_head_sha": freeze["base_v10_head_sha"],
        "actions_attest_commit_sha": freeze["actions"]["attest_commit_sha"],
        "github_attestation_created": False,
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
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE / "LOCAL_RESULT.json",
    )
    args = parser.parse_args()
    receipt = verify(args.output)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
