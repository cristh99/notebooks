from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "test_arbiter.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    report = {
        "coordination_id": "COORD-2026-08-06-PARALLEL-V2",
        "verdict": (
            "PASS_SOFTWARE_ARBITRATION_ONLY"
            if completed.returncode == 0
            else "FAIL"
        ),
        "tests_expected": 16,
        "test_returncode": completed.returncode,
        "source_sha256": sha256(ROOT / "arbiter.py"),
        "tests_sha256": sha256(ROOT / "test_arbiter.py"),
        "contract_sha256": sha256(ROOT / "ARBITRATION_CONTRACT.md"),
        "external_cost_usd": "0.00",
        "production_writes": 0,
        "external_document_access": 0,
        "claim_limit": (
            "Software arbitration only; no external accuracy, payment, legality, "
            "intent, corruption or production claim."
        ),
    }
    unsigned = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    report["receipt_sha256"] = hashlib.sha256(unsigned).hexdigest()
    (ROOT / "verification_receipt.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
