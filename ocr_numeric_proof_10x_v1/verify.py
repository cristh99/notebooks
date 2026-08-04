"""Independent semantic replay of the evidence-grade numeric policy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .policy import build_report, canonical_json, sha256_bytes


def stable_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key != "stable_payload_sha256"
    }


def verify(
    observed_path: Path,
    quality_path: Path,
    artifact_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []
    observed = json.loads(
        observed_path.read_text(encoding="utf-8")
    )
    observed_payload = stable_payload(observed)
    observed_sha = sha256_bytes(
        canonical_json(observed_payload).encode("utf-8")
    )
    if observed.get("stable_payload_sha256") != observed_sha:
        errors.append("observed stable payload hash mismatch")

    rebuilt = build_report(quality_path, artifact_sha256)
    rebuilt_payload = stable_payload(rebuilt)
    if canonical_json(observed_payload) != canonical_json(
        rebuilt_payload
    ):
        errors.append("semantic replay mismatch")

    evaluation = observed_payload.get("evaluation") or {}
    baseline = evaluation.get("baseline") or {}
    policy = evaluation.get("policy") or {}
    reduction = evaluation.get(
        "false_acceptance_error_reduction_factor"
    )
    baseline_error = float(
        baseline.get("false_acceptance_rate", -1)
    )
    policy_error = float(policy.get("false_acceptance_rate", -1))
    if policy_error <= 0:
        rebuilt_reduction = None
    else:
        rebuilt_reduction = baseline_error / policy_error
    if reduction is None:
        if rebuilt_reduction is not None:
            errors.append("error reduction missing")
    elif abs(float(reduction) - float(rebuilt_reduction)) > 1e-12:
        errors.append("error reduction arithmetic mismatch")

    constraints = observed_payload.get("constraints") or {}
    for key in (
        "ocr_rerun",
        "gcloud_used",
        "gpu_used",
        "paid_api_used",
        "logic_power_in_runtime",
    ):
        if constraints.get(key) is not False:
            errors.append(f"constraint changed: {key}")

    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_sha,
        "rebuilt_stable_payload_sha256": rebuilt[
            "stable_payload_sha256"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    args = parser.parse_args()
    result = verify(
        args.report,
        args.quality_report,
        args.artifact_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
