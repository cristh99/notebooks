from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPSTREAM = Path(
    os.environ.get(
        "EVIDENCE_SCOPE_ROOT",
        ROOT.parent / "data_science_pipeline_v9_evidence_scope",
    )
).resolve()
EVIDENCE = ROOT / "evidence"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iter_tests(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def main() -> int:
    freeze = json.loads((ROOT / "FREEZE.json").read_text(encoding="utf-8"))
    adversarial = json.loads(
        (ROOT / "ADVERSARIAL_RESULT.json").read_text(encoding="utf-8")
    )
    sys.path.insert(0, str(UPSTREAM))
    sys.path.insert(0, str(ROOT))

    checks = {
        "upstream_source_hash_exact": sha256(UPSTREAM / "evidence_scope.py")
        == freeze["upstream"]["source_sha256"],
        "source_hash_exact": sha256(ROOT / "signed_validator.py")
        == freeze["source_sha256"],
        "tests_hash_exact": sha256(ROOT / "test_signed_validator.py")
        == freeze["tests_sha256"],
        "verifier_hash_exact": sha256(ROOT / "verify.py")
        == freeze["verify_sha256"],
        "requirements_hash_exact": sha256(ROOT / "requirements.txt")
        == freeze["requirements_sha256"],
        "adversarial_hash_exact": sha256(ROOT / "ADVERSARIAL_RESULT.json")
        == freeze["adversarial"]["report_sha256"],
        "adversarial_cases_exact": adversarial.get("cases")
        == freeze["adversarial"]["cases"],
        "adversarial_verdict_pass": adversarial.get("verdict") == "PASS",
        "adversarial_invariant_violations_zero": adversarial.get(
            "invariant_violations"
        )
        == 0,
        "cryptography_version_exact": importlib.metadata.version("cryptography")
        == freeze["dependency"]["cryptography"],
        "zero_cost_exact": freeze["controls"]["external_cost_usd"] == 0.0,
        "network_required_false": freeze["controls"]["network_required"] is False,
        "real_private_keys_present_false": freeze["controls"][
            "real_private_keys_present"
        ]
        is False,
    }

    suite = unittest.defaultTestLoader.loadTestsFromName("test_signed_validator")
    test_ids = tuple(sorted(test.id() for test in iter_tests(suite)))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    checks["tests_pass"] = (
        result.wasSuccessful()
        and result.testsRun == freeze["expected_tests"]
        and len(test_ids) == freeze["expected_tests"]
    )

    try:
        compile(
            (ROOT / "signed_validator.py").read_text(encoding="utf-8"),
            "signed_validator.py",
            "exec",
        )
        compile(
            (ROOT / "test_signed_validator.py").read_text(encoding="utf-8"),
            "test_signed_validator.py",
            "exec",
        )
        checks["compile_pass"] = True
    except SyntaxError:
        checks["compile_pass"] = False

    verdict = "PASS_SIGNED_VALIDATOR_SOFTWARE_ONLY" if all(checks.values()) else "FAIL"
    receipt = {
        "schema": "data-science-pipeline/signed-validator-local-receipt/2",
        "verdict": verdict,
        "checks": checks,
        "tests_expected": freeze["expected_tests"],
        "test_ids": list(test_ids),
        "adversarial_cases": freeze["adversarial"]["cases"],
        "adversarial_report_sha256": freeze["adversarial"]["report_sha256"],
        "upstream_source_sha256": freeze["upstream"]["source_sha256"],
        "source_sha256": freeze["source_sha256"],
        "tests_sha256": freeze["tests_sha256"],
        "verify_sha256": freeze["verify_sha256"],
        "requirements_sha256": freeze["requirements_sha256"],
        "registry_and_signature_scope": "finite Ed25519 authorization policy",
        "external_cost_usd": 0.0,
        "production_modified": False,
        "real_validator_keys_bound": False,
        "fresh_external_document_still_required": True,
    }
    payload = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "receipt.json").write_text(payload, encoding="utf-8")
    (EVIDENCE / "receipt.sha256").write_text(
        f"{hashlib.sha256(payload.encode()).hexdigest()}  receipt.json\n",
        encoding="utf-8",
    )
    (EVIDENCE / "tests.log").write_text(stream.getvalue(), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if verdict.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
