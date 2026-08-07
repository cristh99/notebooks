#!/usr/bin/env python3
"""Capture the unmodified public-test baseline for one frozen CS1200 pset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def classify(output: str, returncode: int, timed_out: bool) -> str:
    lower = output.lower()
    if timed_out:
        return "TIMEOUT"
    if returncode == 0:
        return "PASS"
    if "modulenotfounderror" in lower or "no module named" in lower:
        return "BLOCKED_MISSING_DEPENDENCY"
    if "syntaxerror" in lower or "indentationerror" in lower:
        return "FAIL_SYNTAX"
    if "notimplementederror" in lower:
        return "FAIL_NOT_IMPLEMENTED"
    if "filenotfounderror" in lower:
        return "BLOCKED_MISSING_FILE"
    if "assertionerror" in lower or "failed" in lower or "tests passed" in lower:
        return "FAIL_PUBLIC_TEST"
    return "FAIL_RUNTIME"


def run_file(pset_dir: Path, test_path: Path, timeout: int) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update(
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
    timed_out = False
    try:
        completed = subprocess.run(
            [sys.executable, test_path.name],
            cwd=pset_dir,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        returncode = completed.returncode
        output = (completed.stdout or "") + (
            "\n" if completed.stdout and completed.stderr else ""
        ) + (completed.stderr or "")
    except subprocess.TimeoutExpired as error:
        timed_out = True
        returncode = 124
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
        output = stdout + ("\n" if stdout and stderr else "") + stderr
    return {
        "test_file": test_path.relative_to(pset_dir.parent.parent).as_posix(),
        "status": classify(output, returncode, timed_out),
        "returncode": returncode,
        "elapsed_seconds": time.perf_counter() - started,
        "timed_out": timed_out,
        "output_sha256": sha256_bytes(output.encode()),
        "output_excerpt": output[-12000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--pset", required=True, type=int, choices=range(6, 11))
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    arguments = parser.parse_args()

    repo = arguments.repo.resolve()
    pset_dir = repo / "psets" / f"ps{arguments.pset}"
    preflight = json.loads(arguments.preflight.read_text())
    assert preflight["status"] == "PASS_SCOPED_SOURCE_PREFLIGHT"
    assert preflight["pset"] == arguments.pset

    test_files = [repo / path for path in preflight["summary"]["test_files"]]
    results = [run_file(pset_dir, path, arguments.timeout) for path in test_files]
    distribution: dict[str, int] = {}
    for row in results:
        distribution[row["status"]] = distribution.get(row["status"], 0) + 1

    if not results:
        baseline_state = "NO_PUBLIC_TEST_FILE_DISCOVERED"
    elif all(row["status"] == "PASS" for row in results):
        baseline_state = "ALL_PUBLIC_TEST_FILES_PASS"
    else:
        baseline_state = "BASELINE_FAILURES_RETAINED"

    report = {
        "schema": "university-cs1200-pset/public-test-baseline/1",
        "status": "PASS_BASELINE_CAPTURED",
        "official_repository": "Harvard-CS-1200/2026-Spring",
        "official_commit": "0b967fe320ecf2141a6f3b8165d3d096c99fb3ac",
        "pset": arguments.pset,
        "baseline_state": baseline_state,
        "test_files": len(results),
        "status_distribution": dict(sorted(distribution.items())),
        "results": results,
        "environment": {
            "python": sys.version,
            "dependencies_installed": False,
            "starter_files_modified": False,
            "timeout_seconds_per_file": arguments.timeout,
        },
        "guardrails": {
            "problem_set_solved": False,
            "problem_set_complete": False,
            "course_complete": False,
            "failures_removed_from_denominator": 0,
            "cost_usd": 0,
        },
        "scope_boundary": (
            "Baseline execution of discovered public tests on official starter code; "
            "not a solution or a problem-set/course completion claim."
        ),
    }
    arguments.out.mkdir(parents=True, exist_ok=True)
    report_path = arguments.out / "baseline.json"
    report_path.write_bytes(stable_bytes(report))
    (arguments.out / "baseline.sha256").write_text(
        f"{sha256_bytes(report_path.read_bytes())}  baseline.json\n"
    )
    for row in results:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", row["test_file"])
        (arguments.out / f"{safe}.log").write_text(row["output_excerpt"])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
