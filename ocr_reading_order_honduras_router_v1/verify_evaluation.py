"""Independent semantic replay of contextual-router evaluation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ocr_reading_order_real_v1.core import canonical_json, sha256_bytes
from .evaluate_holdout import build_report


def verify(
    report_path: Path,
    preparation_path: Path,
    annotations_path: Path,
    artifact_zip: Path | None,
) -> dict[str, Any]:
    errors: list[str] = []
    observed = json.loads(report_path.read_text(encoding="utf-8"))
    observed_payload = {
        key: value for key, value in observed.items() if key != "stable_payload_sha256"
    }
    observed_sha = sha256_bytes(canonical_json(observed_payload).encode("utf-8"))
    if observed.get("stable_payload_sha256") != observed_sha:
        errors.append("stable payload hash mismatch")
    preparation = json.loads(preparation_path.read_text(encoding="utf-8"))
    annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
    rebuilt = build_report(preparation, annotations, artifact_zip)
    rebuilt_payload = {
        key: value for key, value in rebuilt.items() if key != "stable_payload_sha256"
    }
    if canonical_json(observed_payload) != canonical_json(rebuilt_payload):
        errors.append("semantic replay mismatch")
    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_sha,
        "rebuilt_stable_payload_sha256": rebuilt["stable_payload_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument(
        "--annotations",
        type=Path,
        default=Path("ocr_reading_order_honduras_router_v1/annotations.json"),
    )
    parser.add_argument("--artifact-zip", type=Path)
    args = parser.parse_args()
    result = verify(
        args.report,
        args.preparation,
        args.annotations,
        args.artifact_zip,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
