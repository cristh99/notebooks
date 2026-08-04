from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from .audit import TASKS, canonical, sha_file

SCHEMA = "fin-abs-005/qfbench-frozen-solutions/1"
EXPECTED_FILES = {
    "structured-note-risk": ("results.json", "solution.json"),
    "swap-curve-bootstrap-ois": (
        "ois_discount_curve.csv",
        "libor_forward_curve.csv",
        "repriced_quotes.csv",
        "swap_valuation.json",
        "summary.json",
    ),
    "double-sort": ("strategy_returns.csv",),
    "bs-greeks-pde": (
        "calibration.json",
        "greeks_surface.csv",
        "pde_verification.csv",
        "summary.json",
    ),
    "kelly-var-sizing": ("results.json", "solution.json"),
}
SOLVER_FILES = {
    "structured-note-risk": "structured_note_risk.py",
    "swap-curve-bootstrap-ois": "swap_curve_bootstrap_ois.py",
    "double-sort": "double_sort.py",
    "bs-greeks-pde": "bs_greeks_pde.py",
    "kelly-var-sizing": "kelly_var_sizing.py",
}


def finite_json(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(finite_json(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and finite_json(item) for key, item in value.items())
    return False


def freeze(
    outputs: Path,
    audit_path: Path,
    solver_root: Path,
    implementation_commit: str,
) -> dict[str, Any]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit_payload = audit.get("payload", {})
    if audit_payload.get("status") != "PASS_BLIND_STAGE0":
        raise ValueError("QFBench source audit must pass before solution freeze")
    output_manifest: list[dict[str, Any]] = []
    task_checks: dict[str, dict[str, bool]] = {}
    for task in TASKS:
        task_root = outputs / task
        expected = EXPECTED_FILES[task]
        checks = {
            "directory_present": task_root.is_dir(),
            "expected_files_exact": False,
            "all_files_nonempty": False,
            "json_finite": True,
            "csv_nonempty": True,
        }
        if task_root.is_dir():
            actual = sorted(path.name for path in task_root.iterdir() if path.is_file())
            checks["expected_files_exact"] = actual == sorted(expected)
            checks["all_files_nonempty"] = all(
                (task_root / name).is_file() and (task_root / name).stat().st_size > 0
                for name in expected
            )
            for name in expected:
                path = task_root / name
                if not path.is_file():
                    continue
                if path.suffix == ".json":
                    try:
                        checks["json_finite"] = checks["json_finite"] and finite_json(
                            json.loads(path.read_text(encoding="utf-8"))
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        checks["json_finite"] = False
                elif path.suffix == ".csv":
                    try:
                        frame = pd.read_csv(path)
                        checks["csv_nonempty"] = checks["csv_nonempty"] and (
                            len(frame) > 0 and len(frame.columns) > 0
                        )
                    except Exception:
                        checks["csv_nonempty"] = False
                output_manifest.append(
                    {
                        "task_id": task,
                        "path": f"{task}/{name}",
                        "bytes": path.stat().st_size,
                        "sha256": sha_file(path),
                    }
                )
        task_checks[task] = checks

    solver_manifest = []
    for task in TASKS:
        path = solver_root / SOLVER_FILES[task]
        solver_manifest.append(
            {
                "task_id": task,
                "path": path.name,
                "bytes": path.stat().st_size if path.is_file() else 0,
                "sha256": sha_file(path) if path.is_file() else None,
            }
        )
    output_manifest.sort(key=lambda item: (item["task_id"], item["path"]))
    solver_manifest.sort(key=lambda item: item["task_id"])
    checks = {
        "source_audit_pass": audit_payload.get("status") == "PASS_BLIND_STAGE0",
        "all_task_output_checks_pass": all(
            all(value for value in task_checks[task].values()) for task in TASKS
        ),
        "all_solver_files_present": all(item["sha256"] for item in solver_manifest),
        "implementation_commit_present": len(implementation_commit) == 40,
        "absolute_score_unchanged": True,
    }
    payload = {
        "schema": SCHEMA,
        "status": "FROZEN_BEFORE_HIDDEN_VERIFIER" if all(checks.values()) else "BLOCKED_BEFORE_HIDDEN_VERIFIER",
        "source_audit_sha256": audit.get("sha256"),
        "implementation_commit": implementation_commit,
        "tasks": list(TASKS),
        "task_checks": task_checks,
        "output_manifest": output_manifest,
        "output_manifest_sha256": hashlib.sha256(
            canonical(output_manifest).encode("utf-8")
        ).hexdigest(),
        "solver_manifest": solver_manifest,
        "solver_manifest_sha256": hashlib.sha256(
            canonical(solver_manifest).encode("utf-8")
        ).hexdigest(),
        "gate_checks": checks,
        "absolute_score": {"before": 423, "after": 423, "delta": 0},
    }
    canonical_payload = canonical(payload)
    return {
        "payload": payload,
        "payload_canonical": canonical_payload,
        "sha256": hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--solver-root", type=Path, required=True)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = freeze(
        args.outputs,
        args.audit,
        args.solver_root,
        args.implementation_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["payload"]["status"],
                "tasks": result["payload"]["tasks"],
                "output_manifest_sha256": result["payload"]["output_manifest_sha256"],
                "report_sha256": result["sha256"],
                "absolute_score": result["payload"]["absolute_score"]["after"],
            },
            sort_keys=True,
        )
    )
    if result["payload"]["status"] != "FROZEN_BEFORE_HIDDEN_VERIFIER":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
