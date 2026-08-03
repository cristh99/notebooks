from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
from pathlib import Path
from typing import Any

from . import audit as base

SCHEMA = "fin-abs-004/fdic-access-audit/2"


def full_record_url(endpoint: str, date: str | None = None) -> str:
    parameters = {
        "limit": "1",
        "offset": "0",
        "format": "csv",
        "download": "false",
        "filename": "data_file",
    }
    if date is not None:
        parameters["filters"] = f"REPDTE:{date.replace('-', '')}"
    return f"{base.API_BASE}/{endpoint}?{urllib.parse.urlencode(parameters)}"


def documentation_contract(report: dict[str, Any], output: Path) -> dict[str, Any]:
    payload = report["payload"]
    legacy_records = {
        record.get("resource"): record for record in payload.get("acquisitions", [])
    }
    documentation_files = []
    for resource in ("financial_taxonomy", "failure_taxonomy"):
        record = legacy_records.get(resource, {})
        file_name = record.get("file")
        if not file_name:
            continue
        file_path = output / str(file_name)
        if not file_path.exists():
            continue
        raw = file_path.read_bytes()
        text = raw.decode("utf-8", errors="ignore")
        documentation_files.append(
            {
                "resource": resource,
                "file": file_path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "content_type": record.get("content_type"),
                "is_html": "<html" in text.lower() or "<!doctype html" in text.lower(),
                "contains_api_documentation_title": "BankFind Suite - API Documentation" in text,
            }
        )
    same_redirect_body = (
        len(documentation_files) == 2
        and len({item["sha256"] for item in documentation_files}) == 1
    )
    return {
        "legacy_yaml_urls_now_return_html": (
            len(documentation_files) == 2
            and all(item["is_html"] for item in documentation_files)
        ),
        "official_api_documentation_identified": (
            len(documentation_files) == 2
            and all(
                item["contains_api_documentation_title"]
                for item in documentation_files
            )
        ),
        "legacy_urls_redirect_to_same_documentation_body": same_redirect_body,
        "files": documentation_files,
    }


def acquire_live_contract(output: Path) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    for name, url in (
        ("financial_full_record", full_record_url("financials", "2025-12-31")),
        ("failure_full_record", full_record_url("failures")),
    ):
        raw, record = base.fetch_bytes(url)
        record["resource"] = name
        value: dict[str, Any] = {"acquisition": record}
        if raw is not None:
            path = output / f"{name}.csv"
            path.write_bytes(raw)
            value["file"] = path.name
            try:
                frame = base.csv_frame(raw)
                value["rows"] = int(len(frame))
                value["columns"] = sorted(str(column) for column in frame.columns)
                value["column_count"] = len(frame.columns)
            except Exception as exc:  # evidence is recorded; verifier remains fail-closed
                value["parse_error"] = f"{type(exc).__name__}: {exc}"
        resources[name] = value
    return resources


def redesign(report: dict[str, Any], output: Path) -> dict[str, Any]:
    payload = report["payload"]
    documentation = documentation_contract(report, output)
    live = acquire_live_contract(output)
    financial_columns = set(live.get("financial_full_record", {}).get("columns", []))
    failure_columns = set(live.get("failure_full_record", {}).get("columns", []))
    stable_sample_fields = set(payload.get("taxonomies", {}).get("stable_sample_fields", []))
    original_checks = payload.get("gate_checks", {})

    revised_checks = {
        "official_api_documentation_acquired": documentation[
            "official_api_documentation_identified"
        ],
        "obsolete_yaml_redirect_detected": documentation[
            "legacy_yaml_urls_now_return_html"
        ],
        "live_financial_contract_acquired": bool(financial_columns),
        "live_failure_contract_acquired": bool(failure_columns),
        "sample_fields_returned_by_live_financial_contract": set(
            base.SAMPLE_FIELDS
        ).issubset(financial_columns),
        "failure_fields_returned_by_live_failure_contract": set(
            base.FAILURE_FIELDS
        ).issubset(failure_columns),
        "failure_list_acquired": bool(original_checks.get("failure_list_acquired")),
        "failure_dates_parse_at_least_99pct": bool(
            original_checks.get("failure_dates_parse_at_least_99pct")
        ),
        "all_representative_quarters_acquired": bool(
            original_checks.get("all_representative_quarters_acquired")
        ),
        "all_sample_fields_stable": set(base.SAMPLE_FIELDS).issubset(
            stable_sample_fields
        ),
        "zero_sample_bank_quarter_duplicates": bool(
            original_checks.get("zero_sample_bank_quarter_duplicates")
        ),
        "train_failures_at_least_20": bool(
            original_checks.get("train_failures_at_least_20")
        ),
        "validation_failures_at_least_20": bool(
            original_checks.get("validation_failures_at_least_20")
        ),
        "test_failures_at_least_100": bool(
            original_checks.get("test_failures_at_least_100")
        ),
    }
    recommendation = "PROCEED" if all(revised_checks.values()) else "REDESIGN"
    payload["schema"] = SCHEMA
    payload["documentation_contract"] = documentation
    payload["live_api_contract"] = live
    payload["obsolete_taxonomy_contract"] = {
        "previous_status": report["payload"].get("status"),
        "reason": (
            "The two legacy YAML URLs return the official API documentation HTML, "
            "so field existence is verified against live one-record API schemas and "
            "representative-quarter stability instead of pretending HTML is YAML."
        ),
    }
    payload["gate_checks"] = revised_checks
    payload["recommendation"] = recommendation
    payload["status"] = f"STAGE0_{recommendation}"
    payload["absolute_score"] = {
        "before": 423,
        "after": 423,
        "delta": 0,
        "boundary": (
            "Metadata redesign and access audit only; no bank-distress model evaluated."
        ),
    }
    payload_canonical = base.canonical(payload)
    return {
        "payload": payload,
        "payload_canonical": payload_canonical,
        "sha256": hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    original = base.audit(args.output_dir)
    report = redesign(original, args.output_dir)
    path = args.output_dir / "report.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload = report["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "recommendation": payload["recommendation"],
                "failed_gates": sorted(
                    key for key, value in payload["gate_checks"].items() if not value
                ),
                "financial_contract_fields": payload["live_api_contract"]
                ["financial_full_record"].get("column_count", 0),
                "failure_contract_fields": payload["live_api_contract"]
                ["failure_full_record"].get("column_count", 0),
                "failure_rows": payload["failures"]["rows"],
                "report_sha256": report["sha256"],
                "absolute_score": 423,
            },
            sort_keys=True,
        )
    )
    if payload["recommendation"] != "PROCEED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
