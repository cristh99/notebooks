"""Independent semantic replay of the full-content OCR quality audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .full_content_quality import build_report, canonical_json, sha256_bytes


def stable_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"stable_payload_sha256", "environment"}
    }


def verify(
    observed_path: Path,
    stage1_path: Path,
    annotation_path: Path,
    artifact_sha256: str | None,
) -> dict[str, Any]:
    errors: list[str] = []
    observed = json.loads(observed_path.read_text(encoding="utf-8"))
    observed_payload = stable_payload(observed)
    observed_sha = sha256_bytes(
        canonical_json(observed_payload).encode("utf-8")
    )
    if observed.get("stable_payload_sha256") != observed_sha:
        errors.append("observed stable payload hash mismatch")

    rebuilt = build_report(
        stage1_path,
        annotation_path,
        artifact_sha256,
    )
    rebuilt_payload = stable_payload(rebuilt)
    if canonical_json(observed_payload) != canonical_json(rebuilt_payload):
        errors.append("semantic replay mismatch")

    source = observed_payload.get("source") or {}
    if source.get("stage1_artifact_sha256") != artifact_sha256:
        errors.append("Stage 1 artifact binding mismatch")
    constraints = observed_payload.get("constraints") or {}
    for key in (
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
    parser.add_argument("--stage1-report", type=Path, required=True)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--artifact-sha256")
    args = parser.parse_args()
    result = verify(
        args.report,
        args.stage1_report,
        args.annotation,
        args.artifact_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
