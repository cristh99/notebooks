from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "fin-abs-006/qfbench-breadth-selection/1"
SOURCE_COMMIT = "d2fc28b3492f2d73d192fa7eabadf150a19a62fb"
SEED = "FIN-ABS-006-QFBENCH-BREADTH-V1"
COHORT_SIZE = 15
PUBLIC_FRONTIER_PASS_RATE = 0.617
REQUIRED_PASSES = 13
CALIBRATION_TASKS = {
    "structured-note-risk",
    "swap-curve-bootstrap-ois",
    "double-sort",
    "bs-greeks-pde",
    "kelly-var-sizing",
}


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


def rank_key(task_id: str) -> str:
    return hashlib.sha256(f"{SEED}|{task_id}".encode("utf-8")).hexdigest()


def wilson_lower(successes: int, trials: int, z: float = 1.96) -> float:
    if trials <= 0:
        return 0.0
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = proportion + z * z / (2.0 * trials)
    margin = z * math.sqrt(
        (proportion * (1.0 - proportion) + z * z / (4.0 * trials))
        / trials
    )
    return (center - margin) / denominator


def discover_task_ids(source: Path) -> list[str]:
    task_root = source / "tasks"
    if not task_root.is_dir():
        raise ValueError("QFBench sparse checkout has no tasks directory")
    return sorted(
        path.parent.name
        for path in task_root.glob("*/task.toml")
        if path.is_file()
    )


def select(source: Path, observed_commit: str) -> dict[str, Any]:
    discovered = discover_task_ids(source)
    duplicates = len(discovered) - len(set(discovered))
    eligible = sorted(set(discovered) - CALIBRATION_TASKS)
    ranked = sorted(eligible, key=lambda task_id: (rank_key(task_id), task_id))
    selected = ranked[:COHORT_SIZE]
    selection_contract = {
        "source_commit": SOURCE_COMMIT,
        "seed": SEED,
        "cohort_size": COHORT_SIZE,
        "excluded_calibration_tasks": sorted(CALIBRATION_TASKS),
        "selected_tasks": selected,
    }
    checks = {
        "source_commit_exact": observed_commit == SOURCE_COMMIT,
        "discovered_tasks_at_least_80": len(discovered) >= 80,
        "zero_duplicate_task_ids": duplicates == 0,
        "calibration_tasks_present_but_excluded": CALIBRATION_TASKS.issubset(
            discovered
        ) and not (set(selected) & CALIBRATION_TASKS),
        "fifteen_unique_selected": len(selected) == COHORT_SIZE
        and len(set(selected)) == COHORT_SIZE,
        "required_passes_wilson_exceeds_frontier": wilson_lower(
            REQUIRED_PASSES, COHORT_SIZE
        )
        > PUBLIC_FRONTIER_PASS_RATE,
        "absolute_score_unchanged": True,
    }
    payload = {
        "schema": SCHEMA,
        "source": {
            "repository": "QF-Bench/QuantitativeFinance-Bench",
            "commit": SOURCE_COMMIT,
            "observed_commit": observed_commit,
        },
        "discovery": {
            "task_count": len(discovered),
            "task_ids_sha256": digest(discovered),
            "content_fields_read": ["parent_directory_name", "task.toml_presence"],
            "instruction_files_read": 0,
            "solution_files_read": 0,
            "test_files_read": 0,
        },
        "selection": {
            **selection_contract,
            "selection_sha256": digest(selection_contract),
            "ranked_selected": [
                {"task_id": task_id, "rank_sha256": rank_key(task_id)}
                for task_id in selected
            ],
        },
        "promotion_contract": {
            "public_frontier_pass_rate": PUBLIC_FRONTIER_PASS_RATE,
            "required_complete_passes": REQUIRED_PASSES,
            "total_tasks": COHORT_SIZE,
            "required_observed_pass_rate": REQUIRED_PASSES / COHORT_SIZE,
            "required_wilson_lower_95": wilson_lower(
                REQUIRED_PASSES, COHORT_SIZE
            ),
            "hidden_test_repair_permitted": False,
            "score_delta_before_full_independent_gate": 0,
        },
        "gate_checks": checks,
        "status": "COHORT_FROZEN" if all(checks.values()) else "BLOCKED_SELECTION",
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
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--observed-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = select(args.source, args.observed_commit)
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
                "task_count": payload["discovery"]["task_count"],
                "selected_tasks": payload["selection"]["selected_tasks"],
                "selection_sha256": payload["selection"]["selection_sha256"],
                "required_passes": payload["promotion_contract"][
                    "required_complete_passes"
                ],
                "wilson_lower_95": payload["promotion_contract"][
                    "required_wilson_lower_95"
                ],
                "report_sha256": report["sha256"],
                "absolute_score": payload["absolute_score"]["after"],
            },
            sort_keys=True,
        )
    )
    if payload["status"] != "COHORT_FROZEN":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
