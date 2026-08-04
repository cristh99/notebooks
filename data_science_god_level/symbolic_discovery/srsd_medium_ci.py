from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

import numpy as np

SOURCE_COMMIT = "8d562c9ea19be1e9de336e3d2a30000723c5c8f6"
SOURCE_REPOSITORY = "yoshitomo-matsubara/srsd-feynman_medium_dummy"


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _load_runner(code_root: Path):
    sys.path.insert(0, str(code_root))
    import srsd_medium_runner as runner
    return runner


def preflight(code_root: Path, logs: Path) -> None:
    manifest_path = code_root / "SRSD_MEDIUM_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["frozen_from_commit"] == "a133de401d80ff5b1e669181c0e3a685408869d6"
    assert manifest["candidate"]["sha256"] == "97c9fd1a3f371ca30bd29b924ac0e6d1ea21d985e513df8b5de977f0a70be381"
    assert manifest["source"]["commit"] == SOURCE_COMMIT
    assert len(manifest["dataset_ids"]) == 40
    assert manifest["source"]["selection_rule"].startswith("all 40")
    assert manifest["evaluation"]["actual_external_evaluations_authorized"] == 1
    assert manifest["evaluation"]["train_rows_per_task"] == 8000
    assert manifest["evaluation"]["candidate_max_terms"] == 4
    assert manifest["evaluation"]["thresholds"]["candidate_failures_max"] == 0

    tree = ast.parse((code_root / "estimator.py").read_text(encoding="utf-8"))
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
    assert not (imports - {"__future__", "dataclasses", "typing", "numpy"})
    assert not (calls & {"open", "eval", "exec", "compile", "__import__", "system", "popen", "run", "urlopen", "request", "read_csv", "read_json", "load"})
    assert not (names & {"Path", "dataset_name", "filename", "truth", "labels", "requests", "socket", "subprocess", "pandas"})

    source_names = (
        "estimator.py", "srsd_medium_runner.py", "srsd_medium_plan.py",
        "test_srsd_medium_runner.py", "srsd_medium_ci.py", "SRSD_MEDIUM_MANIFEST.json",
    )
    audit = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-medium-static-audit/1",
        "hashes": {name: _digest(code_root / name) for name in source_names},
        "candidate_truth_access": False,
        "candidate_dataset_identifier_access": False,
        "candidate_filesystem_network_process_access": False,
        "candidate_frozen_before_medium_data_access": True,
        "medium_dataset_bytes_accessed_yet": False,
        "dataset_selection_post_hoc": False,
        "easy_suite_reused": False,
    }
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "static-audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "data-science-god-level-srsd-medium-gate/1"})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            if not data:
                raise ValueError(f"empty response: {url}")
            temporary.write_bytes(data)
            temporary.replace(destination)
            return
        except Exception as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < 4:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed after retries: {url}: {last_error}")


def download_and_seal(code_root: Path, data_root: Path, logs: Path) -> None:
    runner = _load_runner(code_root)
    base = f"https://huggingface.co/datasets/{SOURCE_REPOSITORY}/resolve/{SOURCE_COMMIT}"
    for dataset_id in runner.DATASET_IDS:
        slug = runner._slug(dataset_id)
        for split, extension in (("train", "txt"), ("test", "txt"), ("true_eq", "pkl")):
            destination = data_root / split / f"feynman-{slug}.{extension}"
            url = f"{base}/{split}/feynman-{slug}.{extension}?download=true"
            _download(url, destination)

    for split, extension in (("train", "txt"), ("test", "txt"), ("true_eq", "pkl")):
        files = sorted((data_root / split).glob(f"*.{extension}"))
        if len(files) != 40 or any(path.stat().st_size == 0 for path in files):
            raise ValueError(f"invalid downloaded file set: {split}")

    tasks: list[dict[str, object]] = []
    total_bytes = 0
    for dataset_id in runner.DATASET_IDS:
        slug = runner._slug(dataset_id)
        paths = {
            "train": data_root / "train" / f"feynman-{slug}.txt",
            "test": data_root / "test" / f"feynman-{slug}.txt",
            "true_eq": data_root / "true_eq" / f"feynman-{slug}.pkl",
        }
        X_train, y_train = runner._load_table(paths["train"])
        X_test, y_test = runner._load_table(paths["test"])
        truth_variables = runner._safe_symbol_indices(paths["true_eq"])
        expected_dummy_count = runner._dummy_count(dataset_id)
        observed_dummy_count = X_train.shape[1] - len(truth_variables)
        assert X_train.shape[0] == 8000
        assert X_test.shape[0] == 1000
        assert X_train.shape[1] == X_test.shape[1]
        assert observed_dummy_count == expected_dummy_count
        assert np.all(np.isfinite(y_train)) and np.all(np.isfinite(y_test))
        entry: dict[str, object] = {
            "dataset_id": dataset_id,
            "feature_count": int(X_train.shape[1]),
            "train_rows": int(X_train.shape[0]),
            "test_rows": int(X_test.shape[0]),
            "train_target_std": float(np.std(y_train)),
            "test_target_std": float(np.std(y_test)),
            "truth_variable_indices": list(truth_variables),
            "expected_dummy_count": expected_dummy_count,
            "observed_dummy_count": observed_dummy_count,
            "files": {},
        }
        for role, path in paths.items():
            size = path.stat().st_size
            total_bytes += size
            entry["files"][role] = {"bytes": size, "sha256": _digest(path)}  # type: ignore[index]
        tasks.append(entry)

    manifest = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-medium-data-manifest/1",
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": SOURCE_COMMIT,
        "selection_rule": "all 40 SRSD-Feynman Medium Dummy equations",
        "task_count": len(tasks),
        "total_bytes": total_bytes,
        "truth_pickle_executed": False,
        "truth_symbol_extraction": "pickletools opcode scan only",
        "actual_external_evaluation_count_authorized": 1,
        "tasks": tasks,
    }
    (logs / "data-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"task_count": 40, "total_bytes": total_bytes, "truth_pickle_executed": False}, indent=2, sort_keys=True))


def seal_chain(code_root: Path, logs: Path) -> None:
    status_path = logs / "runner-exit-status.txt"
    source_names = (
        "estimator.py", "srsd_medium_runner.py", "srsd_medium_plan.py",
        "srsd-medium-plan-receipt.json", "test_srsd_medium_runner.py",
        "srsd_medium_ci.py", "SRSD_MEDIUM_MANIFEST.json",
    )
    chain = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-medium-chain/1",
        "github_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "github_run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "github_sha": os.environ["GITHUB_SHA"],
        "activation_parent_sha": os.environ["SRSD_MEDIUM_ACTIVATION_PARENT_SHA"],
        "runner_exit_status": int(status_path.read_text().strip()) if status_path.exists() else None,
        "candidate_frozen_before_medium_data_access": True,
        "dataset_selection_post_hoc": False,
        "truth_pickle_executed": False,
        "actual_external_evaluation_count_authorized": 1,
        "easy_suite_reused": False,
        "hashes": {
            **{name: _digest(code_root / name) for name in source_names},
            "static-audit.json": _digest(logs / "static-audit.json"),
            "data-manifest.json": _digest(logs / "data-manifest.json"),
            "srsd-medium-report.json": _digest(logs / "srsd-medium-report.json"),
            "srsd-medium-freeze-receipt.json": _digest(logs / "srsd-medium-freeze-receipt.json"),
        },
    }
    payload = json.dumps(chain, indent=2, sort_keys=True) + "\n"
    (logs / "chain-receipt.json").write_text(payload, encoding="utf-8")
    (logs / "chain-receipt.sha256").write_text(hashlib.sha256(payload.encode()).hexdigest() + "  chain-receipt.json\n", encoding="utf-8")
    print(payload)


def enforce(logs: Path) -> None:
    receipt_path = logs / "srsd-medium-freeze-receipt.json"
    report_path = logs / "srsd-medium-report.json"
    status_path = logs / "runner-exit-status.txt"
    chain_path = logs / "chain-receipt.json"
    if not all(path.exists() for path in (receipt_path, report_path, status_path, chain_path)):
        raise SystemExit("external SRSD Medium evaluation invalid or incomplete; evidence preserved")
    receipt = json.loads(receipt_path.read_text())
    report = json.loads(report_path.read_text())
    chain = json.loads(chain_path.read_text())
    status = int(status_path.read_text().strip())
    assert receipt["actual_external_evaluation_count"] == 1
    assert receipt["candidate_frozen_before_medium_data_access"] is True
    assert receipt["candidate_truth_access"] is False
    assert receipt["truth_pickle_executed"] is False
    assert receipt["post_hoc_retuning_permitted"] is False
    assert receipt["dataset_selection_post_hoc"] is False
    assert receipt["dataset_selection_rule"] == "all 40 SRSD-Feynman Medium Dummy equations"
    assert report["summary"] == receipt["summary"]
    assert chain["github_run_attempt"] == 1
    assert chain["runner_exit_status"] == status
    assert all(value is not None for value in chain["hashes"].values())
    if receipt["verdict"] == "PASS" and status != 0:
        raise SystemExit("PASS receipt conflicts with runner status")
    if receipt["verdict"] == "FAIL" and status == 0:
        raise SystemExit("FAIL receipt conflicts with runner status")
    if receipt["verdict"] != "PASS":
        raise SystemExit(f"external SRSD Medium gate: {receipt['verdict']}; evidence preserved; no retuning")
    print("external SRSD Medium gate: PASS; all 40 tasks evaluated once; no retuning permitted")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "download", "chain", "enforce"))
    parser.add_argument("--code-root", required=True)
    parser.add_argument("--logs-dir", required=True)
    parser.add_argument("--data-root")
    args = parser.parse_args()
    code_root = Path(args.code_root).resolve()
    logs = Path(args.logs_dir).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    if args.command == "preflight":
        preflight(code_root, logs)
    elif args.command == "download":
        if not args.data_root:
            raise SystemExit("--data-root is required for download")
        download_and_seal(code_root, Path(args.data_root).resolve(), logs)
    elif args.command == "chain":
        seal_chain(code_root, logs)
    else:
        enforce(logs)


if __name__ == "__main__":
    main()
