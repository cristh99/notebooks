from __future__ import annotations

import hashlib
import io
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE_DIR = ROOT / "evidence"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_tests(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def main() -> int:
    freeze = json.loads((ROOT / "FREEZE.json").read_text(encoding="utf-8"))
    checks = {
        "source_hash_exact": sha256(ROOT / "evidence_scope.py")
        == freeze["source_sha256"],
        "tests_hash_exact": sha256(ROOT / "test_evidence_scope.py")
        == freeze["tests_sha256"],
        "network_required_false": freeze["controls"]["network_required"] is False,
        "zero_cost_exact": freeze["controls"]["external_cost_usd"] == 0.0,
        "fresh_external_gate_open": freeze["controls"]
        ["fresh_external_document_still_required"]
        is True,
    }

    suite = unittest.defaultTestLoader.loadTestsFromName("test_evidence_scope")
    test_ids = tuple(sorted(test.id() for test in _iter_tests(suite)))
    stream = io.StringIO()
    result = unittest.TextTestRunner(
        stream=stream,
        verbosity=2,
        failfast=False,
    ).run(suite)
    checks["tests_pass"] = (
        result.wasSuccessful()
        and result.testsRun == freeze["expected_tests"]
        and len(test_ids) == freeze["expected_tests"]
    )

    try:
        compile(
            (ROOT / "evidence_scope.py").read_text(encoding="utf-8"),
            "evidence_scope.py",
            "exec",
        )
        compile(
            (ROOT / "test_evidence_scope.py").read_text(encoding="utf-8"),
            "test_evidence_scope.py",
            "exec",
        )
        checks["compile_pass"] = True
    except SyntaxError:
        checks["compile_pass"] = False

    verdict = "PASS_SOFTWARE_POLICY_ONLY" if all(checks.values()) else "FAIL"
    receipt = {
        "schema": "data-science-pipeline/evidence-scope-local-receipt/2",
        "verdict": verdict,
        "checks": checks,
        "tests_expected": freeze["expected_tests"],
        "test_ids": list(test_ids),
        "source_sha256": freeze["source_sha256"],
        "tests_sha256": freeze["tests_sha256"],
        "external_cost_usd": 0.0,
        "production_modified": False,
        "scientific_promotion_credit": 0,
        "fresh_external_document_still_required": True,
    }
    payload = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "receipt.json").write_text(payload, encoding="utf-8")
    (EVIDENCE_DIR / "receipt.sha256").write_text(
        f"{hashlib.sha256(payload.encode('utf-8')).hexdigest()}  receipt.json\n",
        encoding="utf-8",
    )
    (EVIDENCE_DIR / "tests.log").write_text(stream.getvalue(), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if verdict.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
