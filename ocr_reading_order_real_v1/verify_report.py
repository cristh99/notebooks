"""Full semantic replay verifier for OCR Reading Order Real v1.

The verifier reloads the pinned raw annotation, rebuilds the split, candidate
selection, holdout metrics, decision, and stable payload, then compares the
result byte-for-byte at canonical-JSON level. Runtime/environment fields are
intentionally excluded from the proof-carrying payload.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .core import canonical_json, sha256_bytes
from .run_benchmark import build_report, resolve_annotation


def stable_payload(report: dict[str, Any]) -> dict[str, Any]:
    excluded = {"stable_payload_sha256", "runtime", "environment"}
    return {key: value for key, value in report.items() if key not in excluded}


def verify(report_path: Path, annotation: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    observed = json.loads(report_path.read_text(encoding="utf-8"))
    observed_payload = stable_payload(observed)
    observed_sha = sha256_bytes(canonical_json(observed_payload).encode("utf-8"))
    if observed.get("stable_payload_sha256") != observed_sha:
        errors.append("stable_payload_sha256 mismatch")

    annotation_path = resolve_annotation(annotation)
    rebuilt = build_report(annotation_path)
    rebuilt_payload = stable_payload(rebuilt)
    if canonical_json(observed_payload) != canonical_json(rebuilt_payload):
        errors.append("semantic replay mismatch")

    solver = observed_payload.get("solver") or {}
    solver_payload = {key: value for key, value in solver.items() if key != "receipt_sha256"}
    solver_sha = sha256_bytes(canonical_json(solver_payload).encode("utf-8"))
    if solver.get("receipt_sha256") != solver_sha:
        errors.append("solver receipt mismatch")

    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_sha,
        "rebuilt_stable_payload_sha256": rebuilt.get("stable_payload_sha256"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--annotation", type=Path)
    args = parser.parse_args()
    result = verify(args.report, args.annotation)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
