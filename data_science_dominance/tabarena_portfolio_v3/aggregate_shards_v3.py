from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
TASKS_PATH = ROOT / "tasks_v3.json"
EXPECTED_CANDIDATE_SHA256 = "6b5927a854c5b2d565a6065f6c8807134ef52cf03e77803c7d6fcdc4b78a96ff"
EXPECTED_TASKS_SHA256 = "8204cc0611a1c3f7bc6d3186295f4f4876cc8f01c965d49775a1c9b8ccff3edd"
PRIOR_RUN_ID = 30975732979
PRIOR_JOB_ID = 92209219630
THRESHOLDS = {
    "task_count": 12,
    "candidate_failures_max": 0,
    "tabiclv2_success_count_min": 12,
    "mean_advantage_min": -0.003,
    "median_advantage_min": 0.0,
    "wins_or_ties_min": 8,
    "clear_wins_min": 2,
    "worst_advantage_min": -0.02,
    "classification_gap_to_best_mean_min": 0.003,
    "regression_gap_to_best_mean_min": 0.001,
    "minimum_anchor_weight": 0.55,
    "total_runtime_seconds_max": 18000.0,
}


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    successful = [row for row in rows if "error" not in row]
    failures = len(rows) - len(successful)
    advantages = np.asarray([float(row["advantage"]) for row in successful], dtype=float)
    classification = [row for row in successful if row["category"] == "classification"]
    regression = [row for row in successful if row["category"] == "regression"]
    model_names = sorted({name for row in successful for name in row["individuals"]})

    def mean_candidate(group):
        return float(np.mean([row["candidate"]["score"] for row in group])) if group else float("nan")

    def model_mean(group, name):
        values = [row["individuals"][name]["score"] for row in group if name in row["individuals"]]
        return float(np.mean(values)) if values else float("nan")

    class_candidate = mean_candidate(classification)
    reg_candidate = mean_candidate(regression)
    class_model_means = {name: model_mean(classification, name) for name in model_names}
    reg_model_means = {name: model_mean(regression, name) for name in model_names}
    best_class_mean = max(class_model_means.values()) if class_model_means else float("nan")
    best_reg_mean = max(reg_model_means.values()) if reg_model_means else float("nan")
    anchor_weights = [float(row["anchor_weight"]) for row in successful]
    tabicl_success = sum("tabiclv2" in row["individuals"] for row in successful)
    return {
        "task_count": len(rows),
        "successful_task_count": len(successful),
        "candidate_failures": failures,
        "tabiclv2_success_count": tabicl_success,
        "mean_advantage": float(np.mean(advantages)) if advantages.size else float("-inf"),
        "median_advantage": float(np.median(advantages)) if advantages.size else float("-inf"),
        "wins_or_ties": int(np.sum(advantages >= -1e-12)) if advantages.size else 0,
        "clear_wins": int(np.sum(advantages > 0.002)) if advantages.size else 0,
        "worst_advantage": float(np.min(advantages)) if advantages.size else float("-inf"),
        "classification_candidate_mean": class_candidate,
        "classification_model_means": class_model_means,
        "classification_best_individual_mean": best_class_mean,
        "classification_gap_to_best_mean": float(class_candidate - best_class_mean),
        "regression_candidate_mean": reg_candidate,
        "regression_model_means": reg_model_means,
        "regression_best_individual_mean": best_reg_mean,
        "regression_gap_to_best_mean": float(reg_candidate - best_reg_mean),
        "minimum_anchor_weight": float(min(anchor_weights)) if anchor_weights else 0.0,
        "mean_anchor_weight": float(np.mean(anchor_weights)) if anchor_weights else 0.0,
        "total_runtime_seconds": float(sum(float(row.get("elapsed_seconds", 0.0)) for row in rows)),
        "finite_all": bool(all(row.get("finite", False) for row in successful) and failures == 0),
    }


def adjudicate(summary: dict[str, object]) -> tuple[dict[str, bool], str]:
    checks = {
        "task_count": int(summary["task_count"]) == THRESHOLDS["task_count"],
        "candidate_failures": int(summary["candidate_failures"]) <= THRESHOLDS["candidate_failures_max"],
        "tabiclv2_success_count": int(summary["tabiclv2_success_count"]) >= THRESHOLDS["tabiclv2_success_count_min"],
        "mean_advantage": float(summary["mean_advantage"]) >= THRESHOLDS["mean_advantage_min"],
        "median_advantage": float(summary["median_advantage"]) >= THRESHOLDS["median_advantage_min"],
        "wins_or_ties": int(summary["wins_or_ties"]) >= THRESHOLDS["wins_or_ties_min"],
        "clear_wins": int(summary["clear_wins"]) >= THRESHOLDS["clear_wins_min"],
        "worst_advantage": float(summary["worst_advantage"]) >= THRESHOLDS["worst_advantage_min"],
        "classification_gap_to_best_mean": float(summary["classification_gap_to_best_mean"]) >= THRESHOLDS["classification_gap_to_best_mean_min"],
        "regression_gap_to_best_mean": float(summary["regression_gap_to_best_mean"]) >= THRESHOLDS["regression_gap_to_best_mean_min"],
        "minimum_anchor_weight": float(summary["minimum_anchor_weight"]) >= THRESHOLDS["minimum_anchor_weight"],
        "total_runtime_seconds": float(summary["total_runtime_seconds"]) <= THRESHOLDS["total_runtime_seconds_max"],
        "finite_all": bool(summary["finite_all"]),
    }
    return checks, "PASS" if all(checks.values()) else "FAIL"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    contract = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    expected = contract["tasks"]
    if len(expected) != 12 or digest(TASKS_PATH) != EXPECTED_TASKS_SHA256:
        raise SystemExit("frozen task contract mismatch")
    if digest(ROOT / "dominance_v3.py") != EXPECTED_CANDIDATE_SHA256:
        raise SystemExit("frozen candidate mismatch")

    files = sorted(args.shards_dir.rglob("shard-*.json"))
    envelopes: dict[int, dict[str, object]] = {}
    source_files: dict[int, Path] = {}
    errors: list[str] = []
    for path in files:
        try:
            envelope = json.loads(path.read_text())
            index = int(envelope["index"])
            if index in envelopes:
                errors.append(f"duplicate shard index {index}")
                continue
            if envelope.get("candidate_sha256") != EXPECTED_CANDIDATE_SHA256:
                errors.append(f"candidate hash mismatch in shard {index}")
                continue
            if envelope.get("tasks_sha256") != EXPECTED_TASKS_SHA256:
                errors.append(f"task hash mismatch in shard {index}")
                continue
            if not 0 <= index < 12:
                errors.append(f"invalid shard index {index}")
                continue
            if envelope.get("task_spec") != expected[index]:
                errors.append(f"task spec mismatch in shard {index}")
                continue
            if int(envelope.get("actual_task_evaluation_count", 0)) != 1:
                errors.append(f"invalid task evaluation count in shard {index}")
                continue
            envelopes[index] = envelope
            source_files[index] = path
        except Exception as error:
            errors.append(f"{path}: {type(error).__name__}: {error}")

    missing = [index for index in range(12) if index not in envelopes]
    complete = not missing and not errors and len(envelopes) == 12
    rows = [envelopes[index]["row"] for index in range(12)] if complete else []

    if complete:
        summary = summarize(rows)
        checks, verdict = adjudicate(summary)
        actual = 1
    else:
        summary = None
        checks = {"complete_shard_set": False}
        verdict = "INVALID_RUN"
        actual = 0

    report = {
        "schema": "data-science-dominance/tabarena-fresh12-v3-report/1",
        "verdict": verdict,
        "thresholds": THRESHOLDS,
        "checks": checks,
        "summary": summary,
        "tasks": rows,
        "contract_sha256": digest(TASKS_PATH),
        "openml_version": "0.15.1",
        "actual_external_evaluation_count": actual,
        "execution_mode": "twelve-independent-shards",
        "prior_aborted_run_id": PRIOR_RUN_ID,
        "prior_aborted_job_id": PRIOR_JOB_ID,
        "missing_shards": missing,
        "aggregation_errors": errors,
        "post_hoc_retuning_permitted": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    score_after = 490 if verdict == "PASS" else 465
    receipt = {
        "schema": "data-science-dominance/tabarena-fresh12-v3-sharded-freeze/1",
        "verdict": verdict,
        "score_before": 465,
        "score_after": score_after,
        "score_if_pass": 490,
        "novelty_points": 0,
        "actual_external_evaluation_count": actual,
        "candidate_frozen_before_task_values": True,
        "task_selection_frozen_before_task_values": True,
        "post_hoc_retuning_permitted": False,
        "prior_aborted_run": {
            "run_id": PRIOR_RUN_ID,
            "job_id": PRIOR_JOB_ID,
            "adjudicable_external_evaluation_count": 0,
            "report_emitted": False,
            "task_row_emitted": False,
            "artifact_count": 0,
            "failure_signal": 143,
        },
        "shard_count_expected": 12,
        "shard_count_received": len(envelopes),
        "missing_shards": missing,
        "aggregation_errors": errors,
        "github_run_id": int(os.environ.get("GITHUB_RUN_ID", "0")),
        "github_run_attempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "0")),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "summary": summary,
        "checks": checks,
        "hashes": {
            "candidate_sha256": digest(ROOT / "dominance_v3.py"),
            "tasks_sha256": digest(ROOT / "tasks_v3.json"),
            "runner_sha256": digest(ROOT / "runner_v3.py"),
            "source_manifest_sha256": digest(ROOT / "SOURCE_MANIFEST_V3.json"),
            "development_receipt_sha256": digest(ROOT / "DEVELOPMENT_RECEIPT_V3.json"),
            "retry_authorization_sha256": digest(ROOT / "INFRASTRUCTURE_RETRY_AUTHORIZATION.json"),
            "report_sha256": digest(args.output),
            "shards": {str(index): digest(source_files[index]) for index in sorted(source_files)},
        },
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    args.receipt.write_text(payload)
    args.receipt.with_suffix(args.receipt.suffix + ".sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + f"  {args.receipt.name}\n"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
