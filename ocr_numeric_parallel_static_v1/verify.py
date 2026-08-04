"""Independent replay for the explicit one-thread Paddle Static benchmark."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping

from ocr_god_10x_quality_v1.full_content_quality import (
    canonical_json,
    sha256_bytes,
)
from ocr_numeric_parallel_10x_v1 import balanced
from ocr_numeric_parallel_10x_v1 import verify_balanced

from .benchmark import (
    MAX_PP_EFFECTIVE_CPU_PARALLELISM,
    PP_ENGINE,
    PP_ENGINE_CONFIG,
    SCHEMA,
    decision_from,
    stable_payload,
    thread_evidence,
)


def verify_report(
    report: Mapping[str, Any],
    *,
    quality_report_path: Path,
    speed_frontier_report_path: Path,
    quality_artifact_sha256: str,
    speed_artifact_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []

    observed_digest = report.get("stable_payload_sha256")
    rebuilt_digest = sha256_bytes(
        canonical_json(stable_payload(report)).encode("utf-8")
    )
    if report.get("schema") != SCHEMA:
        errors.append("schema mismatch")
    if observed_digest != rebuilt_digest:
        errors.append("stable payload digest mismatch")

    projected = copy.deepcopy(dict(report))
    projected["schema"] = balanced.SCHEMA
    projected["decision"] = balanced.decision_from(projected)
    projected["stable_payload_sha256"] = sha256_bytes(
        canonical_json(balanced.stable_payload(projected)).encode("utf-8")
    )
    base_result = verify_balanced.verify_report(
        projected,
        quality_report_path=quality_report_path,
        speed_frontier_report_path=speed_frontier_report_path,
        quality_artifact_sha256=quality_artifact_sha256,
        speed_artifact_sha256=speed_artifact_sha256,
    )
    if not base_result["valid"]:
        errors.extend(f"balanced replay: {error}" for error in base_result["errors"])

    rebuilt_thread_evidence = thread_evidence(report)
    if rebuilt_thread_evidence != report.get("thread_evidence"):
        errors.append("thread evidence replay mismatch")

    contract = report.get("runtime_contract") or {}
    if contract.get("pp_inference_engine") != PP_ENGINE:
        errors.append("PP inference engine mismatch")
    if contract.get("pp_engine_config") != PP_ENGINE_CONFIG:
        errors.append("PP engine config mismatch")
    if bool(contract.get("hpi_enabled")):
        errors.append("HPI remained enabled")
    if float(
        rebuilt_thread_evidence["maximum_allowed_effective_cpu_parallelism"]
    ) != MAX_PP_EFFECTIVE_CPU_PARALLELISM:
        errors.append("thread evidence threshold mismatch")

    rebuilt_decision = decision_from(
        {
            **report,
            "thread_evidence": rebuilt_thread_evidence,
        }
    )
    decision = report.get("decision") or {}
    for field in (
        "quality_gate",
        "concurrency_parity_gate",
        "frozen_drift_detected",
        "thread_gate",
        "runtime_gate",
        "promotion_gate",
        "verdict",
    ):
        if decision.get(field) != rebuilt_decision.get(field):
            errors.append(f"decision mismatch: {field}")

    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_digest,
        "rebuilt_stable_payload_sha256": rebuilt_digest,
        "quality_gate": rebuilt_decision["quality_gate"],
        "concurrency_parity_gate": rebuilt_decision[
            "concurrency_parity_gate"
        ],
        "thread_gate": rebuilt_decision["thread_gate"],
        "runtime_gate": rebuilt_decision["runtime_gate"],
        "promotion_gate": rebuilt_decision["promotion_gate"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--speed-frontier-report", type=Path, required=True)
    parser.add_argument("--quality-artifact-sha256", required=True)
    parser.add_argument("--speed-artifact-sha256", required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = verify_report(
        report,
        quality_report_path=args.quality_report,
        speed_frontier_report_path=args.speed_frontier_report,
        quality_artifact_sha256=args.quality_artifact_sha256,
        speed_artifact_sha256=args.speed_artifact_sha256,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
