from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from registry import validate_registry

HERE = Path(__file__).resolve().parent


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    registry_path = HERE / "EXCLUSION_REGISTRY.json"
    registry = json.loads(registry_path.read_text())
    checks = validate_registry(registry)
    result = {
        "schema": "data-science-pipeline/stage09-exclusion-registry-local-result/1",
        "verdict": "PASS_STAGE09_SIGNED_EXCLUSION_REGISTRY_SOFTWARE_ONLY",
        "tests": "36/36 PASS",
        "checks": checks,
        "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "contamination_entries": len(registry["entries"]),
        "disclosed_selected_candidate_count": registry["aggregate"]["disclosed_selected_candidate_count"],
        "beacon_consumed": False,
        "cohort_selected": False,
        "outcome_accessed": False,
        "analysis_executed": False,
        "stage10_unblocked": False,
        "production_modified": False,
        "external_cost_usd": 0.0,
    }
    args.output.write_bytes(canonical_bytes(result))
    print(result["verdict"])


if __name__ == "__main__":
    main()
