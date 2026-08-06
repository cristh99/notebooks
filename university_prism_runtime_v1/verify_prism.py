#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
SOLVER_OPTIONS = ("-explicit", "-epsilon", "1e-12", "-absolute")
RESULT_RE = re.compile(
    r"^Result(?:\s+\([^)]*\))?:\s*"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
    re.MULTILINE,
)
ERROR_RE = re.compile(r"(^|\n)Error:", re.IGNORECASE)

CASES: tuple[dict[str, Any], ...] = (
    {
        "name": "dtmc_reachability",
        "model": "dtmc_reach.pm",
        "properties": "dtmc_reach.pctl",
        "property_index": 1,
        "expected": 0.4,
    },
    {
        "name": "mdp_min_reachability",
        "model": "mdp_choice.pm",
        "properties": "mdp_choice.pctl",
        "property_index": 1,
        "expected": 0.2,
    },
    {
        "name": "mdp_max_reachability",
        "model": "mdp_choice.pm",
        "properties": "mdp_choice.pctl",
        "property_index": 2,
        "expected": 0.9,
    },
    {
        "name": "dtmc_expected_reward",
        "model": "dtmc_reward.pm",
        "properties": "dtmc_reward.pctl",
        "property_index": 1,
        "expected": 2.0,
    },
    {
        "name": "ctmc_bounded_reachability",
        "model": "ctmc_two_state.pm",
        "properties": "ctmc_two_state.csl",
        "property_index": 1,
        "expected": 1.0 - math.exp(-2.0),
    },
    {
        "name": "ctmc_steady_state",
        "model": "ctmc_two_state.pm",
        "properties": "ctmc_two_state.csl",
        "property_index": 2,
        "expected": 2.0 / 3.0,
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_case(prism: Path, case: dict[str, Any]) -> dict[str, Any]:
    command = [
        str(prism),
        str(MODELS / case["model"]),
        str(MODELS / case["properties"]),
        "-prop",
        str(case["property_index"]),
        *SOLVER_OPTIONS,
    ]
    start = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = time.perf_counter() - start
    matches = RESULT_RE.findall(completed.stdout)
    if completed.returncode != 0 or ERROR_RE.search(completed.stdout):
        raise RuntimeError(
            f"{case['name']} failed with code {completed.returncode}\n"
            f"{completed.stdout}"
        )
    if len(matches) != 1:
        raise RuntimeError(
            f"{case['name']} produced {len(matches)} numeric results; expected one\n"
            f"{completed.stdout}"
        )
    token = matches[0]
    value = float(token)
    return {
        "name": case["name"],
        "command": command,
        "returncode": completed.returncode,
        "result_token": token,
        "value": value,
        "expected": float(case["expected"]),
        "absolute_error": abs(value - float(case["expected"])),
        "elapsed_seconds": elapsed,
        "stdout": completed.stdout,
    }


def run_suite(prism: Path, parallel: bool, workers: int) -> tuple[list[dict[str, Any]], float]:
    start = time.perf_counter()
    if parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_case, prism, case): case for case in CASES}
            unordered = [future.result() for future in concurrent.futures.as_completed(futures)]
        results = sorted(unordered, key=lambda item: item["name"])
    else:
        results = sorted((run_case(prism, case) for case in CASES), key=lambda item: item["name"])
    return results, time.perf_counter() - start


def write_logs(directory: Path, results: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for result in results:
        (directory / f"{result['name']}.log").write_text(result["stdout"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prism", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    args = parser.parse_args()

    prism = args.prism.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    version_run = subprocess.run(
        [str(prism), "-version"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    (out / "prism-version.log").write_text(version_run.stdout)

    serial, serial_seconds = run_suite(prism, parallel=False, workers=args.workers)
    parallel, parallel_seconds = run_suite(prism, parallel=True, workers=args.workers)
    write_logs(out / "serial", serial)
    write_logs(out / "parallel", parallel)

    serial_map = {item["name"]: item for item in serial}
    parallel_map = {item["name"]: item for item in parallel}
    oracle_failures: list[str] = []
    parity_failures: list[str] = []
    for name in sorted(serial_map):
        serial_item = serial_map[name]
        parallel_item = parallel_map[name]
        if serial_item["absolute_error"] > args.tolerance:
            oracle_failures.append(name)
        if abs(serial_item["value"] - parallel_item["value"]) > 1e-15:
            parity_failures.append(name)

    invalid_command = [
        str(prism),
        str(MODELS / "invalid_distribution.pm"),
        str(MODELS / "invalid_distribution.pctl"),
        "-prop",
        "1",
        *SOLVER_OPTIONS,
    ]
    invalid = subprocess.run(
        invalid_command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (out / "negative-control.log").write_text(invalid.stdout)
    invalid_results = RESULT_RE.findall(invalid.stdout)
    negative_control_rejected = (
        invalid.returncode != 0
        or (ERROR_RE.search(invalid.stdout) is not None and not invalid_results)
    )

    model_hashes = {
        path.name: sha256(path)
        for path in sorted(MODELS.iterdir())
        if path.is_file()
    }
    report = {
        "schema": "university-prism-runtime/report/1",
        "status": (
            "PASS_SCOPED_PRISM_RUNTIME"
            if not oracle_failures and not parity_failures and negative_control_rejected
            else "FAIL"
        ),
        "prism_version_output": version_run.stdout.strip(),
        "engine": "explicit",
        "solver_options": list(SOLVER_OPTIONS),
        "tolerance": args.tolerance,
        "workers": args.workers,
        "serial_seconds": serial_seconds,
        "parallel_seconds": parallel_seconds,
        "speedup": serial_seconds / parallel_seconds if parallel_seconds else None,
        "serial_parallel_payload_equal": not parity_failures,
        "oracle_failures": oracle_failures,
        "parity_failures": parity_failures,
        "negative_control_rejected": negative_control_rejected,
        "negative_control_returncode": invalid.returncode,
        "negative_control_error_marker": ERROR_RE.search(invalid.stdout) is not None,
        "negative_control_result_count": len(invalid_results),
        "results": [
            {
                key: value
                for key, value in item.items()
                if key not in {"stdout", "command"}
            }
            for item in serial
        ],
        "model_sha256": model_hashes,
        "scope_boundary": (
            "Finite DTMC, MDP, CTMC, rewards and one invalid model; "
            "not the complete PRISM language or Oxford course."
        ),
    }
    report_path = out / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "report.sha256").write_text(f"{sha256(report_path)}  report.json\n")
    print(json.dumps(report, indent=2, sort_keys=True))

    return 0 if report["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
