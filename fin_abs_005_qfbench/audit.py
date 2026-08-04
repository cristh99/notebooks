from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

SCHEMA = "fin-abs-005/qfbench-blind-audit/1"
SOURCE_REPOSITORY = "QF-Bench/QuantitativeFinance-Bench"
SOURCE_COMMIT = "d2fc28b3492f2d73d192fa7eabadf150a19a62fb"
SEED = "FIN-ABS-005-QFBENCH-CALIBRATION-V1"
TASKS = (
    "structured-note-risk",
    "swap-curve-bootstrap-ois",
    "double-sort",
    "bs-greeks-pde",
    "kelly-var-sizing",
)
EXPECTED_SELECTION_SHA256 = (
    "ece4ec97f61fa1e0c3422498024207734aaa167b90d5587944b436672da79474"
)


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def selection_payload() -> dict[str, Any]:
    return {
        "seed": SEED,
        "source_commit": SOURCE_COMMIT,
        "tasks": list(TASKS),
    }


def workspace_files(source: Path) -> list[Path]:
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and ".git" not in path.relative_to(source).parts
    )


def audit(
    source: Path,
    observed_commit: str = SOURCE_COMMIT,
) -> dict[str, Any]:
    files = workspace_files(source)
    relative = [path.relative_to(source).as_posix() for path in files]
    forbidden = [
        name
        for name in relative
        if "/solution/" in f"/{name}" or "/tests/" in f"/{name}"
    ]
    tasks: list[dict[str, Any]] = []
    missing: list[str] = []
    for task in TASKS:
        root = source / "tasks" / task
        instruction = root / "instruction.md"
        metadata = root / "task.toml"
        environment = root / "environment"
        for required in (instruction, metadata, environment):
            if not required.exists():
                missing.append(required.relative_to(source).as_posix())
        if not instruction.is_file() or not metadata.is_file():
            continue
        parsed = tomllib.loads(metadata.read_text(encoding="utf-8"))
        environment_files = (
            sorted(
                path
                for path in environment.rglob("*")
                if path.is_file()
                and ".git" not in path.relative_to(source).parts
            )
            if environment.is_dir()
            else []
        )
        tasks.append(
            {
                "task_id": task,
                "task_toml_sha256": sha_file(metadata),
                "instruction_sha256": sha_file(instruction),
                "instruction_bytes": instruction.stat().st_size,
                "environment_file_count": len(environment_files),
                "environment_manifest": [
                    {
                        "path": path.relative_to(source).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": sha_file(path),
                    }
                    for path in environment_files
                ],
                "metadata": {
                    "version": parsed.get("version"),
                    "name": parsed.get("metadata", {}).get("name")
                    if isinstance(parsed.get("metadata"), dict)
                    else None,
                    "category": parsed.get("metadata", {}).get("category")
                    if isinstance(parsed.get("metadata"), dict)
                    else None,
                },
            }
        )

    selection = selection_payload()
    selection_sha = digest(selection)
    checks = {
        "source_commit_exact": observed_commit == SOURCE_COMMIT,
        "selection_manifest_exact": selection_sha
        == EXPECTED_SELECTION_SHA256,
        "five_unique_tasks": len(TASKS) == 5 and len(set(TASKS)) == 5,
        "all_selected_tasks_present": len(tasks) == len(TASKS) and not missing,
        "instructions_nonempty": all(
            item["instruction_bytes"] > 100 for item in tasks
        ),
        "environments_present": all(
            item["environment_file_count"] > 0 for item in tasks
        ),
        "zero_solution_or_test_files": not forbidden,
        "root_license_present": (source / "LICENSE").is_file(),
        "root_readme_present": (source / "README.md").is_file(),
    }
    manifest = [
        {
            "path": path.relative_to(source).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha_file(path),
        }
        for path in files
    ]
    payload = {
        "schema": SCHEMA,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "commit": SOURCE_COMMIT,
            "observed_commit": observed_commit,
        },
        "selection": {
            **selection,
            "sha256": selection_sha,
        },
        "workspace": {
            "file_count": len(files),
            "file_manifest": manifest,
            "file_manifest_sha256": digest(manifest),
            "forbidden_paths": forbidden,
            "missing_paths": missing,
        },
        "tasks": tasks,
        "gate_checks": checks,
        "status": (
            "PASS_BLIND_STAGE0"
            if all(checks.values())
            else "BLOCKED_BLIND_STAGE0"
        ),
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": (
                "Source and anti-leakage audit only; no QFBench task has been solved or scored."
            ),
        },
    }
    canonical_payload = canonical(payload)
    return {
        "payload": payload,
        "payload_canonical": canonical_payload,
        "sha256": hashlib.sha256(
            canonical_payload.encode("utf-8")
        ).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--observed-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.source, args.observed_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload = report["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "tasks": [item["task_id"] for item in payload["tasks"]],
                "forbidden_paths": payload["workspace"]["forbidden_paths"],
                "observed_commit": payload["source"]["observed_commit"],
                "report_sha256": report["sha256"],
                "absolute_score": payload["absolute_score"]["after"],
            },
            sort_keys=True,
        )
    )
    if payload["status"] != "PASS_BLIND_STAGE0":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
