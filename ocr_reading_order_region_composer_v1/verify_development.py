"""Independent semantic replay of the region-composer development report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ocr_reading_order_real_v1.core import canonical_json, sha256_bytes
from .development_replay import build_report


def stable_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"stable_payload_sha256", "runtime"}
    }


def verify(
    report_path: Path,
    set1_preparation_path: Path,
    set1_annotations_path: Path,
    set2_preparation_path: Path,
    set2_annotations_path: Path,
    set1_artifact: Path | None,
    set2_artifact: Path | None,
) -> dict[str, Any]:
    errors: list[str] = []
    observed = json.loads(report_path.read_text(encoding="utf-8"))
    observed_payload = stable_payload(observed)
    observed_sha = sha256_bytes(canonical_json(observed_payload).encode("utf-8"))
    if observed.get("stable_payload_sha256") != observed_sha:
        errors.append("stable payload hash mismatch")

    rebuilt = build_report(
        json.loads(set1_preparation_path.read_text(encoding="utf-8")),
        json.loads(set1_annotations_path.read_text(encoding="utf-8")),
        json.loads(set2_preparation_path.read_text(encoding="utf-8")),
        json.loads(set2_annotations_path.read_text(encoding="utf-8")),
        set1_artifact,
        set2_artifact,
    )
    rebuilt_payload = stable_payload(rebuilt)
    if canonical_json(observed_payload) != canonical_json(rebuilt_payload):
        errors.append("semantic replay mismatch")

    solver = observed_payload.get("solver") or {}
    solver_payload = {key: value for key, value in solver.items() if key != "receipt_sha256"}
    solver_sha = sha256_bytes(canonical_json(solver_payload).encode("utf-8"))
    if solver.get("receipt_sha256") != solver_sha:
        errors.append("solver receipt hash mismatch")

    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_sha,
        "rebuilt_stable_payload_sha256": rebuilt["stable_payload_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--set1-preparation", type=Path, required=True)
    parser.add_argument("--set1-annotations", type=Path, required=True)
    parser.add_argument("--set2-preparation", type=Path, required=True)
    parser.add_argument("--set2-annotations", type=Path, required=True)
    parser.add_argument("--set1-artifact", type=Path)
    parser.add_argument("--set2-artifact", type=Path)
    args = parser.parse_args()
    result = verify(
        args.report,
        args.set1_preparation,
        args.set1_annotations,
        args.set2_preparation,
        args.set2_annotations,
        args.set1_artifact,
        args.set2_artifact,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
