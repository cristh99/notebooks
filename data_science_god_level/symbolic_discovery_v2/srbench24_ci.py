from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any

CANDIDATE_SHA256 = "4e80f120c08581d10497e916a86464062df157d99ec6215ad6f7bfd1b7ea557d"
SOURCE_ARCHIVE_B64_SHA256 = "b2a2f9604165f60b869d41c8913442f4d1f52598f746d213247970fa8380bd06"
SOURCE_ARCHIVE_SHA256 = "103e282beb5a59898b4be34334e8449e572271b20063029b47dda1267e72bd0f"


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def preflight(code_root: Path, logs: Path) -> None:
    source_manifest = load_json(code_root / "SOURCE_MANIFEST.json")
    contract = load_json(code_root / "SRBENCH24_MANIFEST.json")
    if source_manifest["candidate"]["sha256"] != CANDIDATE_SHA256:
        raise ValueError("source manifest candidate mismatch")
    if contract["candidate"]["sha256"] != CANDIDATE_SHA256:
        raise ValueError("external contract candidate mismatch")
    if contract["evaluation"]["actual_external_evaluations_authorized"] != 1:
        raise ValueError("external evaluation count must equal one")
    if len(contract["benchmark"]["blackbox"]) != 12:
        raise ValueError("black-box dataset contract is incomplete")
    if len(contract["benchmark"]["firstprinciples"]) != 12:
        raise ValueError("first-principles dataset contract is incomplete")

    candidate_path = code_root / "estimator.py"
    if digest(candidate_path) != CANDIDATE_SHA256:
        raise ValueError("candidate hash mismatch")
    tree = ast.parse(candidate_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imports.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    allowed_imports = {
        "__future__",
        "collections",
        "dataclasses",
        "functools",
        "itertools",
        "math",
        "typing",
        "numpy",
    }
    forbidden_calls = {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "system",
        "popen",
        "run",
        "urlopen",
        "request",
        "read_csv",
        "read_json",
        "load",
    }
    forbidden_names = {
        "Path",
        "dataset_name",
        "filename",
        "truth",
        "labels",
        "requests",
        "socket",
        "subprocess",
        "pandas",
    }
    if imports - allowed_imports:
        raise ValueError(f"candidate import surface expanded: {sorted(imports - allowed_imports)}")
    if calls & forbidden_calls:
        raise ValueError(f"candidate has forbidden calls: {sorted(calls & forbidden_calls)}")
    if names & forbidden_names:
        raise ValueError(f"candidate has forbidden names: {sorted(names & forbidden_names)}")

    source_names = (
        "SOURCE_MANIFEST.json",
        "SRBENCH24_MANIFEST.json",
        "estimator.py",
        "srbench24_runner.py",
        "srbench24_data.py",
        "srbench24_plan.py",
        "test_srbench24.py",
        "srbench24_ci.py",
    )
    audit = {
        "schema": "data-science-god-level/symbolic-v2-srbench24-static-audit/1",
        "hashes": {name: digest(code_root / name) for name in source_names},
        "source_archive_b64_sha256": SOURCE_ARCHIVE_B64_SHA256,
        "source_archive_decoded_sha256": SOURCE_ARCHIVE_SHA256,
        "candidate_truth_access": False,
        "candidate_dataset_identifier_access": False,
        "candidate_filesystem_network_process_access": False,
        "candidate_frozen_before_dataset_values": True,
        "dataset_values_accessed_yet": False,
        "dataset_selection_post_hoc": False,
        "actual_external_evaluations_authorized": 1,
    }
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "static-audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


def finalize(code_root: Path, logs: Path) -> dict[str, Any]:
    status_path = logs / "runner-exit-status.txt"
    report_path = logs / "srbench24-report.json"
    data_manifest_path = logs / "data-manifest.json"
    plan_path = code_root / "srbench24-plan-receipt.json"
    report = load_json(report_path) if report_path.exists() else None
    actual_count = int(report.get("actual_external_evaluation_count", 0)) if report else 0
    verdict = str(report.get("verdict", "INVALID_RUN")) if report else "INVALID_RUN"
    chain = {
        "schema": "data-science-god-level/symbolic-v2-srbench24-chain/1",
        "github_run_id": int(os.environ.get("GITHUB_RUN_ID", "0")),
        "github_run_attempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "0")),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "activation_parent_sha": os.environ.get("SRBENCH24_ACTIVATION_PARENT_SHA"),
        "runner_exit_status": int(status_path.read_text().strip()) if status_path.exists() else None,
        "actual_external_evaluation_count": actual_count,
        "verdict": verdict,
        "candidate_frozen_before_dataset_values": True,
        "dataset_selection_post_hoc": False,
        "post_hoc_retuning_permitted": False,
        "candidate_truth_access": False,
        "candidate_dataset_identifier_access": False,
        "candidate_filesystem_network_process_access": False,
        "paid_compute": False,
        "hashes": {
            "SOURCE_MANIFEST.json": digest(code_root / "SOURCE_MANIFEST.json"),
            "SRBENCH24_MANIFEST.json": digest(code_root / "SRBENCH24_MANIFEST.json"),
            "estimator.py": digest(code_root / "estimator.py"),
            "srbench24_runner.py": digest(code_root / "srbench24_runner.py"),
            "srbench24_data.py": digest(code_root / "srbench24_data.py"),
            "srbench24_plan.py": digest(code_root / "srbench24_plan.py"),
            "srbench24-plan-receipt.json": digest(plan_path),
            "test_srbench24.py": digest(code_root / "test_srbench24.py"),
            "srbench24_ci.py": digest(code_root / "srbench24_ci.py"),
            "static-audit.json": digest(logs / "static-audit.json"),
            "data-manifest.json": digest(data_manifest_path),
            "srbench24-report.json": digest(report_path),
        },
    }
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "chain.json").write_text(
        json.dumps(chain, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema": "data-science-god-level/symbolic-v2-srbench24-freeze/1",
        "verdict": verdict,
        "actual_external_evaluation_count": actual_count,
        "checks": report.get("checks") if report else {"report_exists": False},
        "summary": report.get("summary") if report else None,
        "thresholds": report.get("thresholds") if report else None,
        "candidate_sha256": CANDIDATE_SHA256,
        "report_sha256": digest(report_path),
        "data_manifest_sha256": digest(data_manifest_path),
        "plan_receipt_sha256": digest(plan_path),
        "static_audit_sha256": digest(logs / "static-audit.json"),
        "chain_sha256": digest(logs / "chain.json"),
        "candidate_frozen_before_dataset_values": True,
        "post_hoc_retuning_permitted": False,
        "score_before": 570,
        "score_change_authorized_here": 0,
    }
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    (logs / "freeze-receipt.json").write_text(payload, encoding="utf-8")
    (logs / "freeze-receipt.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "  freeze-receipt.json\n",
        encoding="utf-8",
    )
    print(payload)
    return receipt


def enforce(logs: Path) -> None:
    receipt_path = logs / "freeze-receipt.json"
    if not receipt_path.exists():
        raise SystemExit("external receipt missing")
    receipt = load_json(receipt_path)
    if receipt["actual_external_evaluation_count"] != 1:
        raise SystemExit("external evaluation was not completed exactly once")
    if receipt["verdict"] != "PASS":
        raise SystemExit(f"SRBench-24 gate: {receipt['verdict']}; evidence preserved; no retuning")
    print("SRBench-24 gate: PASS; candidate remains frozen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "finalize", "enforce"))
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--logs-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "preflight":
        preflight(args.code_root, args.logs_dir)
    elif args.mode == "finalize":
        finalize(args.code_root, args.logs_dir)
    else:
        enforce(args.logs_dir)


if __name__ == "__main__":
    main()
