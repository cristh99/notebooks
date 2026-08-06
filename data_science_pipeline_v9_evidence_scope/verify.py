from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE_DIR = ROOT / "evidence"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    freeze = json.loads((ROOT / "FREEZE.json").read_text(encoding="utf-8"))
    checks = {
        "source_hash_exact": sha256(ROOT / "evidence_scope.py") == freeze["source_sha256"],
        "tests_hash_exact": sha256(ROOT / "test_evidence_scope.py") == freeze["tests_sha256"],
        "network_required_false": freeze["controls"]["network_required"] is False,
        "zero_cost_exact": freeze["controls"]["external_cost_usd"] == 0.0,
        "fresh_external_gate_open": freeze["controls"]["fresh_external_document_still_required"] is True,
    }
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "test_evidence_scope.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    test_log = completed.stdout + completed.stderr
    checks["tests_pass"] = completed.returncode == 0 and "Ran 8 tests" in test_log and "OK" in test_log
    compile_completed = subprocess.run(
        [sys.executable, "-m", "py_compile", "evidence_scope.py", "test_evidence_scope.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    checks["compile_pass"] = compile_completed.returncode == 0

    verdict = "PASS_SOFTWARE_POLICY_ONLY" if all(checks.values()) else "FAIL"
    receipt = {
        "schema": "data-science-pipeline/evidence-scope-local-receipt/1",
        "verdict": verdict,
        "python_version": sys.version.split()[0],
        "checks": checks,
        "tests_expected": freeze["expected_tests"],
        "source_sha256": freeze["source_sha256"],
        "tests_sha256": freeze["tests_sha256"],
        "external_cost_usd": 0.0,
        "production_modified": False,
        "scientific_promotion_credit": 0,
        "fresh_external_document_still_required": True,
        "test_log_sha256": hashlib.sha256(test_log.encode("utf-8")).hexdigest(),
    }
    payload = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "receipt.json").write_text(payload, encoding="utf-8")
    (EVIDENCE_DIR / "receipt.sha256").write_text(
        f"{hashlib.sha256(payload.encode('utf-8')).hexdigest()}  receipt.json\n",
        encoding="utf-8",
    )
    (EVIDENCE_DIR / "tests.log").write_text(test_log, encoding="utf-8")
    print(payload, end="")
    return 0 if verdict.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
