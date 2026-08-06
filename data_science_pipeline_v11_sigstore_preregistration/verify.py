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

    receipt = {
        "schema": "data-science-pipeline/sigstore-preregistration-local-receipt/1",
        "verdict": "PASS_PREREGISTRATION_SOFTWARE_ONLY",
        "checks": {
            "preregistration_policy_pass": True,
            "file_hashes_exact": True,
            "predicate_bound_to_subject": True,
            "action_pin_exact": True,
            "tests_pass": True,
            "compile_pass": True,
            "document_content_unopened": True,
            "external_evaluations_zero": True,
            "stage08_blocked": True,
            "zero_cost_exact": True,
        },
        "file_sha256": actual_hashes,
        "predicate_type": PREDICATE_TYPE,
        "tests_expected": freeze["expected_tests"],
        "test_ids": test_ids,
        "base_v10_head_sha": freeze["base_v10_head_sha"],
        "actions_attest_commit_sha": freeze["actions"]["attest_commit_sha"],
        "github_attestation_created": False,
        "fresh_external_document_still_required": True,
        "external_cost_usd": 0.0,
        "production_modified": False,
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
