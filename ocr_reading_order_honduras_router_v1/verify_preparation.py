"""Fail-closed verifier for the independent router-holdout preparation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ocr_reading_order_real_v1.core import canonical_json, sha256_bytes
from .router import route


def verify(report_path: Path, manifest_path: Path, template_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    payload = {key: value for key, value in report.items() if key != "stable_payload_sha256"}
    observed_sha = sha256_bytes(canonical_json(payload).encode("utf-8"))
    if report.get("stable_payload_sha256") != observed_sha:
        errors.append("stable payload hash mismatch")
    manifest_sha = sha256_bytes(manifest_bytes)
    if report.get("manifest_sha256") != manifest_sha:
        errors.append("manifest hash mismatch")
    if template.get("manifest_sha256") != manifest_sha:
        errors.append("template manifest mismatch")
    if manifest.get("selection_frozen_before_page_review") is not True:
        errors.append("selection was not declared frozen")

    documents = manifest.get("documents") or []
    ids = [str(item["id"]) for item in documents]
    if len(ids) != len(set(ids)):
        errors.append("duplicate manifest IDs")
    if sorted({int(item["source_record_line"]) for item in documents}) != [6, 7, 8, 9, 10]:
        errors.append("source record set drift")
    if any(item.get("page_rule") not in {"FIRST", "LAST"} for item in documents):
        errors.append("invalid page rule")

    observations = report.get("observations") or []
    if report.get("documents_declared") != len(observations):
        errors.append("declared denominator mismatch")
    prepared = [item for item in observations if item.get("status") == "PREPARED"]
    if report.get("documents_prepared") != len(prepared):
        errors.append("prepared denominator mismatch")
    templates = {item["document_id"]: item for item in template.get("annotations") or []}

    for item in prepared:
        document_id = item["document"]["id"]
        blocks = item.get("blocks") or []
        block_ids = [str(block["block_id"]) for block in blocks]
        if len(block_ids) < 2 or len(block_ids) != len(set(block_ids)):
            errors.append(f"invalid blocks: {document_id}")
            continue
        for field in ("baseline_order", "geometry_order", "router_order"):
            order = [str(value) for value in item.get(field) or []]
            if len(order) != len(block_ids) or set(order) != set(block_ids):
                errors.append(f"{field} is not a permutation: {document_id}")
        page = item.get("page") or {}
        decision = route(blocks, float(page.get("page_width") or 0), float(page.get("page_height") or 0))
        expected = {
            "baseline_order": list(decision.baseline_order),
            "geometry_order": list(decision.geometry_order),
            "router_order": list(decision.selected_order),
            "router_selected": decision.selected,
            "router_reason": decision.reason,
            "router_disagreement_blocks": list(decision.disagreement_blocks),
            "router_features": decision.features,
        }
        for field, value in expected.items():
            if canonical_json(item.get(field)) != canonical_json(value):
                errors.append(f"router replay mismatch {field}: {document_id}")
        annotation = templates.get(document_id)
        if annotation is None:
            errors.append(f"missing annotation template: {document_id}")
        elif annotation.get("available_block_ids") != block_ids:
            errors.append(f"template block denominator mismatch: {document_id}")
    if len(templates) != len(prepared):
        errors.append("template document count mismatch")

    constraints = report.get("constraints") or {}
    expected_constraints = {
        "external_spend_usd": 0,
        "gcloud_used": False,
        "paid_api_used": False,
        "gpu_used": False,
        "second_ocr_pass_used": False,
        "logic_power_in_runtime": False,
        "production_path_modified": False,
    }
    for key, value in expected_constraints.items():
        if constraints.get(key) != value:
            errors.append(f"constraint violation: {key}")
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
