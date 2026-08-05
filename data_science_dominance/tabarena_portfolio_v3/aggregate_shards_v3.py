from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import runner_v3

EXPECTED_CANDIDATE_SHA256 = "6b5927a854c5b2d565a6065f6c8807134ef52cf03e77803c7d6fcdc4b78a96ff"
EXPECTED_TASKS_SHA256 = "8204cc0611a1c3f7bc6d3186295f4f4876cc8f01c965d49775a1c9b8ccff3edd"
PRIOR_RUN_ID = 30975732979
PRIOR_JOB_ID = 92209219630


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    contract = runner_v3.load_contract()
    expected = contract["tasks"]
    files = sorted(args.shards_dir.rglob("shard-*.json"))
    envelopes: dict[int, dict[str, object]] = {}
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
            spec = envelope.get("task_spec")
            if spec != expected[index]:
                errors.append(f"task spec mismatch in shard {index}")
                continue
            envelopes[index] = envelope
        except Exception as error:
            errors.append(f"{path}: {type(error).__name__}: {error}")

    missing = [index for index in range(12) if index not in envelopes]
    complete = not missing and not errors and len(envelopes) == 12
    rows = [envelopes[index]["row"] for index in range(12)] if complete else []

    if complete:
        summary = runner_v3.summarize(rows)
        checks, verdict = runner_v3.adjudicate(summary)
        actual = 1
    else:
        summary = None
        checks = {"complete_shard_set": False}
        verdict = "INVALID_RUN"
        actual = 0

    report = {
        "schema": "data-science-dominance/tabarena-fresh12-v3-report/1",
        "verdict": verdict,
        "thresholds": runner_v3.THRESHOLDS,
        "checks": checks,
        "summary": summary,
        "tasks": rows,
        "contract_sha256": runner_v3.sha256(runner_v3.TASKS_PATH),
        "openml_version": __import__("openml").__version__,
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

    shard_hashes = {
        str(index): digest(next(path for path in files if path.name == f"shard-{index}.json"))
        for index in sorted(envelopes)
    }
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
            "shards": shard_hashes,
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
