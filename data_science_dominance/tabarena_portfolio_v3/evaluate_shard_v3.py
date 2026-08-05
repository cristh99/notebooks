from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

import runner_v3

CANDIDATE_SHA256 = "6b5927a854c5b2d565a6065f6c8807134ef52cf03e77803c7d6fcdc4b78a96ff"
TASKS_SHA256 = "8204cc0611a1c3f7bc6d3186295f4f4876cc8f01c965d49775a1c9b8ccff3edd"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.index < 12:
        raise SystemExit("shard index must be in [0, 11]")
    if sha256(ROOT / "dominance_v3.py") != CANDIDATE_SHA256:
        raise SystemExit("candidate hash mismatch")
    if sha256(ROOT / "tasks_v3.json") != TASKS_SHA256:
        raise SystemExit("task contract hash mismatch")
    contract = runner_v3.load_contract()
    spec = contract["tasks"][args.index]
    try:
        row = runner_v3.evaluate_one(spec)
    except Exception as error:
        row = {
            "dataset": spec["dataset"],
            "task_id": spec["task_id"],
            "problem_type": spec["problem_type"],
            "repeat": spec.get("repeat", 0),
            "fold": spec.get("fold", 0),
            "sample": spec.get("sample", 0),
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
            "finite": False,
            "elapsed_seconds": 0.0,
        }
    envelope = {
        "schema": "data-science-dominance/tabarena-v3-shard/1",
        "index": args.index,
        "candidate_sha256": CANDIDATE_SHA256,
        "tasks_sha256": TASKS_SHA256,
        "task_spec": spec,
        "actual_task_evaluation_count": 1,
        "post_hoc_retuning_permitted": False,
        "row": row,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
    print(json.dumps(envelope, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
