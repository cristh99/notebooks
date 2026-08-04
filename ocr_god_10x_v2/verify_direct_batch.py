"""Independent arithmetic replay of the direct batched OCR benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from ocr_reading_order_real_v1.core import canonical_json

from .benchmark import _sha256_text, aggregate, page_metrics
from .direct_batch import SPECS, direct_gate


def verify(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = report.get("observations") or []
    if len(rows) != 20:
        errors.append(f"expected 20 observations, found {len(rows)}")
    page_ids = [str(row.get("page_id")) for row in rows]
    if len(page_ids) != len(set(page_ids)):
        errors.append("duplicate page identities")

    engine_names = ["tesseract", *SPECS]
    for row in rows:
        reference = str(row.get("reference_text") or "")
        if row.get("reference_sha256") != _sha256_text(reference):
            errors.append(f"reference hash mismatch: {row.get('page_id')}")
        engines = row.get("engines") or {}
        for engine in engine_names:
            observed = engines.get(engine)
            if not isinstance(observed, Mapping):
                errors.append(f"missing engine {engine}: {row.get('page_id')}")
                continue
            text = str(observed.get("text") or "")
            rebuilt = page_metrics(reference, text)
            if canonical_json(rebuilt) != canonical_json(observed.get("metrics")):
                errors.append(f"metric mismatch: {row.get('page_id')} {engine}")
            runtime = observed.get("runtime") or {}
            if float(runtime.get("wall_seconds", -1)) < 0 or float(runtime.get("cpu_seconds", -1)) < 0:
                errors.append(f"invalid runtime: {row.get('page_id')} {engine}")

    aggregates = {name: aggregate(rows, name) for name in engine_names} if rows else {}
    if canonical_json(aggregates) != canonical_json(report.get("aggregate")):
        errors.append("aggregate mismatch")
    if aggregates:
        baseline = aggregates["tesseract"]
        rebuilt_gates = {
            name: direct_gate(baseline, aggregates[name])
            for name in SPECS
        }
        observed_gates = (report.get("decision") or {}).get("gates")
        if canonical_json(rebuilt_gates) != canonical_json(observed_gates):
            errors.append("gate mismatch")

    totals = report.get("direct_stage_totals") or {}
    for name in SPECS:
        total = totals.get(name)
        if not isinstance(total, Mapping):
            errors.append(f"missing direct stage total: {name}")
            continue
        stage_sum = (
            float(total.get("detection_wall_seconds", 0))
            + float(total.get("crop_wall_seconds", 0))
            + float(total.get("recognition_wall_seconds", 0))
        )
        if abs(stage_sum - float(total.get("total_wall_seconds", -1))) > 1e-9:
            errors.append(f"stage wall sum mismatch: {name}")
        if int(total.get("pages", -1)) != 20:
            errors.append(f"stage page denominator mismatch: {name}")

    payload = {
        key: value
        for key, value in report.items()
        if key not in {"stable_payload_sha256", "environment"}
    }
    observed_hash = _sha256_text(canonical_json(payload))
    if observed_hash != report.get("stable_payload_sha256"):
        errors.append("stable payload hash mismatch")

    constraints = report.get("constraints") or {}
    for key in (
        "gcloud_used",
        "gpu_used",
        "paid_api_used",
        "native_text_counted",
        "cache_hits_counted",
        "repeated_pages_counted",
        "logic_power_in_runtime",
    ):
        if constraints.get(key) is not False:
            errors.append(f"constraint changed: {key}")

    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = verify(args.report)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
