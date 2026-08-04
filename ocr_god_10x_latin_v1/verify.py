"""Independent arithmetic replay for the Latin OCR benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from ocr_god_10x_quality_v1.full_content_quality import canonical_json, sha256_bytes

from .benchmark import LIMITS, aggregate, gate, page_metrics


def verify(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = report.get("observations") or []
    if len(rows) != 20:
        errors.append(f"expected 20 observations, found {len(rows)}")
    page_ids = [str(row.get("page_id")) for row in rows]
    if len(page_ids) != len(set(page_ids)):
        errors.append("duplicate page identities")

    engines = ["tesseract", *(f"latin_{limit}" for limit in LIMITS)]
    for row in rows:
        reference = row.get("reference") or {}
        observed_engines = row.get("engines") or {}
        for engine in engines:
            observed = observed_engines.get(engine)
            if not isinstance(observed, Mapping):
                errors.append(f"missing engine {engine}: {row.get('page_id')}")
                continue
            text = str(observed.get("text") or "")
            rebuilt = page_metrics(reference, text)
            if canonical_json(rebuilt) != canonical_json(observed.get("metrics")):
                errors.append(f"page metric mismatch: {row.get('page_id')} {engine}")
            runtime = observed.get("runtime") or {}
            if float(runtime.get("wall_seconds", -1)) < 0 or float(runtime.get("cpu_seconds", -1)) < 0:
                errors.append(f"invalid runtime: {row.get('page_id')} {engine}")

    rebuilt_aggregate = {engine: aggregate(rows, engine) for engine in engines} if rows else {}
    if canonical_json(rebuilt_aggregate) != canonical_json(report.get("aggregate")):
        errors.append("aggregate mismatch")
    if rebuilt_aggregate:
        baseline = rebuilt_aggregate["tesseract"]
        rebuilt_gates = {
            engine: gate(baseline, rebuilt_aggregate[engine])
            for engine in engines
            if engine != "tesseract"
        }
        if canonical_json(rebuilt_gates) != canonical_json((report.get("decision") or {}).get("gates")):
            errors.append("gate mismatch")

    payload = {
        key: value
        for key, value in report.items()
        if key not in {"stable_payload_sha256", "environment"}
    }
    observed_hash = sha256_bytes(canonical_json(payload).encode("utf-8"))
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
