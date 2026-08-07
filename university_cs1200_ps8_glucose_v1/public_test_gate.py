from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--solution", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()

    shutil.copy2(args.solution, args.official_dir / "ps8.py")
    env = os.environ.copy()
    env.update(
        {
            "PYTHONHASHSEED": "0",
            "MPLBACKEND": "Agg",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "ps8_tests", "3"],
        cwd=args.official_dir,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=1800,
    )
    elapsed = time.perf_counter() - started
    clean = ANSI_RE.sub("", completed.stdout)
    args.log.write_text(clean)

    passed_lines = 0
    failed = 0
    timeouts = 0
    for line in clean.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Tests Passed"):
            continue
        if re.search(r"\bPassed\b", stripped):
            passed_lines += 1
        elif re.search(r"\bFailed\b", stripped):
            failed += 1
        elif re.search(r"\bTimeout\b", stripped):
            timeouts += 1

    summary_matches = [
        (int(left), int(right))
        for left, right in re.findall(r"Tests Passed\s+(\d+)/(\d+)", clean)
    ]
    summary_passed = sum(left for left, _ in summary_matches)
    summary_total = sum(right for _, right in summary_matches)
    passed = max(passed_lines, summary_passed)
    denominator = max(passed + failed + timeouts, summary_total + timeouts)

    if completed.returncode != 0:
        status = "FAIL_PUBLIC_TEST_PROCESS"
    elif failed:
        status = "FAIL_PUBLIC_TEST_FUNCTIONAL"
    elif passed == 0 or denominator == 0:
        status = "FAIL_NO_PUBLIC_TEST_RESULT"
    elif timeouts:
        status = "PASS_PUBLIC_TEST_REPLAY_WITH_RETAINED_TIMEOUTS"
    else:
        status = "PASS_PUBLIC_TEST_REPLAY"

    report = {
        "schema": "university-cs1200-ps8-glucose/public-test-report/1",
        "status": status,
        "returncode": completed.returncode,
        "passed": passed,
        "failed": failed,
        "timeouts": timeouts,
        "denominator": denominator,
        "individual_pass_lines": passed_lines,
        "official_runner_summaries": [
            {"passed": left, "counted_total": right}
            for left, right in summary_matches
        ],
        "official_timeout_seconds_per_case": 10,
        "timeouts_removed_from_denominator": 0,
        "output_sha256": hashlib.sha256(clean.encode()).hexdigest(),
        "elapsed_seconds": elapsed,
        "scope_boundary": (
            "Exact public ps8_tests.py replay after replacing only ps8.py; retained "
            "timeouts are benchmark evidence, not silently discarded targets."
        ),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
