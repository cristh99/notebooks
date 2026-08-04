from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from . import benchmark as engine
from .serialization import canonical_json


def bind_preflight(
    report: dict[str, Any],
    preflight: dict[str, Any],
    entity_report: dict[str, Any],
) -> dict[str, Any]:
    preflight_payload = preflight.get("payload", {})
    entity_payload = entity_report.get("payload", {})
    if preflight_payload.get("status") != "PASS_PREFLIGHT":
        raise ValueError("FDIC sealed benchmark requires PASS_PREFLIGHT")
    if entity_payload.get("status") != "PASS_ENTITY_SPLIT":
        raise ValueError("FDIC sealed benchmark requires PASS_ENTITY_SPLIT")
    preflight_checks = preflight_payload.get("gate_checks", {})
    entity_checks = entity_payload.get("gate_checks", {})
    if not preflight_checks or not all(preflight_checks.values()):
        raise ValueError("one or more FDIC preflight gates failed")
    if not entity_checks or not all(entity_checks.values()):
        raise ValueError("one or more FDIC entity-split gates failed")

    payload = report["payload"]
    source = payload.setdefault("source", {})
    source["preflight_report_sha256"] = preflight.get("sha256")
    source["entity_split_report_sha256"] = entity_report.get("sha256")
    source["entity_split_seed"] = entity_payload.get("protocol", {}).get("seed")
    source["entity_overlap_counts"] = preflight_payload.get(
        "entity_overlap_counts"
    )

    gates = payload.setdefault("python_gate_checks", {})
    gates["preflight_pass"] = True
    gates["entity_split_pass"] = True
    gates["zero_entity_overlap"] = bool(
        preflight_checks.get("zero_entity_overlap")
    )
    gates["entity_split_source_hash_exact"] = bool(
        entity_checks.get("source_panel_hash_exact")
    )
    gates["entity_split_positive_event_sufficiency"] = all(
        bool(entity_checks.get(key))
        for key in (
            "train_positive_entities_at_least_30",
            "validation_positive_entities_at_least_10",
            "test_positive_entities_at_least_50",
            "validation_positive_rows_at_least_20",
            "test_positive_rows_at_least_100",
        )
    )

    candidate_pass = all(bool(value) for value in gates.values())
    payload["performance_candidate_pass"] = candidate_pass
    payload["status"] = (
        "CANDIDATE_PASS_PENDING_INDEPENDENT_MODEL_REPLAY"
        if candidate_pass
        else "FALSIFIED_OR_OPEN_ON_FDIC"
    )
    canonical = canonical_json(payload)
    return {
        "payload": payload,
        "payload_canonical": canonical,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--panel-report", type=Path, required=True)
    parser.add_argument("--preflight-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    preflight = json.loads(args.preflight_report.read_text(encoding="utf-8"))
    entity_report = json.loads(args.panel_report.read_text(encoding="utf-8"))
    report = engine.benchmark(args.panel, args.panel_report, args.output_dir)
    bound = bind_preflight(report, preflight, entity_report)
    report_path = args.output_dir / "report.json"
    report_path.write_text(
        json.dumps(bound, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    payload = bound["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "selected_baseline": payload["validation"][
                    "selected_baseline"
                ],
                "selected_challenger": payload["validation"][
                    "selected_challenger"
                ],
                "candidate_pass": payload["performance_candidate_pass"],
                "zero_entity_overlap": payload["python_gate_checks"][
                    "zero_entity_overlap"
                ],
                "report_sha256": bound["sha256"],
                "absolute_score": payload["absolute_score"]["after"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
