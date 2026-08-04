"""Independent arithmetic and semantic replay of the OCR 10X report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from ocr_reading_order_real_v1.core import canonical_json

from .benchmark import (
    MODEL_SPECS,
    _sha256_text,
    aggregate,
    decide,
    page_metrics,
)


def verify(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = report.get("observations") or []
    if len(rows) != 20:
        errors.append(f"expected 20 observations, found {len(rows)}")

    page_ids = [str(row.get("page_id")) for row in rows]
    if len(set(page_ids)) != len(page_ids):
        errors.append("duplicate page identities")

    engine_names = ["tesseract", *MODEL_SPECS]
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
            rebuilt_metrics = page_metrics(reference, text)
            if canonical_json(rebuilt_metrics) != canonical_json(observed.get("metrics")):
                errors.append(f"page metric mismatch: {row.get('page_id')} {engine}")
            runtime = observed.get("runtime") or {}
            if float(runtime.get("wall_seconds", -1)) < 0 or float(runtime.get("cpu_seconds", -1)) < 0:
                errors.append(f"invalid runtime: {row.get('page_id')} {engine}")

    rebuilt_aggregate = {engine: aggregate(rows, engine) for engine in engine_names} if rows else {}
    if canonical_json(rebuilt_aggregate) != canonical_json(report.get("aggregate")):
        errors.append("aggregate mismatch")
    rebuilt_decision = decide(rebuilt_aggregate) if rebuilt_aggregate else {}
    if canonical_json(rebuilt_decision) != canonical_json(report.get("decision")):
        errors.append("decision mismatch")

    payload = {
        key: value
        for key, value in report.items()
        if key not in {"stable_payload_sha256", "environment"}
    }
    observed_hash = _sha256_text(canonical_json(payload))
    if observed_hash != report.get("stable_payload_sha256"):
        errors.append("stable payload hash mismatch")

    primary = report.get("primary_gate") or {}
    forbidden = {
        "native_text_counted": False,
        "cache_hits_counted": False,
        "repeated_pages_counted": False,
        "paid_api_used": False,
        "gpu_used": False,
        "gcloud_used": False,
    }
    for key, expected in forbidden.items():
        if primary.get(key) is not expected:
            errors.append(f"primary gate boundary changed: {key}")

    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_hash,
        "rebuilt_decision": rebuilt_decision,
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
