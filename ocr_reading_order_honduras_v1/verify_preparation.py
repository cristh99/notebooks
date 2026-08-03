"""Fail-closed verifier for the frozen Honduran preparation artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ocr_reading_order_real_v1.core import canonical_json, sha256_bytes


def verify(report_path: Path, manifest_path: Path, template_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest_bytes = manifest_path.read_bytes()
    template = json.loads(template_path.read_text(encoding="utf-8"))
    payload = {key: value for key, value in report.items() if key != "stable_payload_sha256"}
    observed_sha = sha256_bytes(canonical_json(payload).encode("utf-8"))
    if report.get("stable_payload_sha256") != observed_sha:
        errors.append("stable payload hash mismatch")
    manifest_sha = sha256_bytes(manifest_bytes)
    if report.get("manifest_sha256") != manifest_sha:
        errors.append("manifest hash mismatch")
    if template.get("manifest_sha256") != manifest_sha:
        errors.append("annotation template manifest mismatch")
    observations = report.get("observations") or []
    prepared = [item for item in observations if item.get("status") == "PREPARED"]
    if report.get("documents_declared") != len(observations):
        errors.append("declared document denominator mismatch")
    if report.get("documents_prepared") != len(prepared):
        errors.append("prepared document denominator mismatch")
    templates = {item["document_id"]: item for item in template.get("annotations") or []}
    for item in prepared:
        document_id = item["document"]["id"]
        block_ids = [block["block_id"] for block in item.get("blocks") or []]
        if len(block_ids) < 2 or len(block_ids) != len(set(block_ids)):
            errors.append(f"invalid block IDs: {document_id}")
        for field in ("baseline_order", "geometry_order"):
            order = item.get(field) or []
            if len(order) != len(block_ids) or set(order) != set(block_ids):
                errors.append(f"{field} is not a permutation: {document_id}")
        annotation = templates.get(document_id)
        if annotation is None:
            errors.append(f"missing annotation template: {document_id}")
        elif annotation.get("available_block_ids") != block_ids:
            errors.append(f"annotation block denominator mismatch: {document_id}")
    if len(templates) != len(prepared):
        errors.append("annotation template count mismatch")
    constraints = report.get("constraints") or {}
    if constraints.get("external_spend_usd") != 0:
        errors.append("nonzero spend declared")
    if constraints.get("gcloud_used") is not False:
        errors.append("GCloud constraint violated")
    return {"valid": not errors, "errors": errors, "stable_payload_sha256": observed_sha}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("template", type=Path)
    args = parser.parse_args()
    result = verify(args.report, args.manifest, args.template)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
