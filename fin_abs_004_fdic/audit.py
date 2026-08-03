from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

SCHEMA = "fin-abs-004/fdic-access-audit/1"
API_BASE = "https://banks.data.fdic.gov/api"
FINANCIAL_TAXONOMY = "https://banks.data.fdic.gov/docs/risview_properties.yaml"
FAILURE_TAXONOMY = "https://banks.data.fdic.gov/docs/failure_properties.yaml"
USER_AGENT = "FIN-ABS-004 academic benchmark contact: publicdatafeedback@fdic.gov"
SAMPLE_DATES = (
    "1992-12-31",
    "2000-12-31",
    "2008-12-31",
    "2013-12-31",
    "2025-12-31",
)
SAMPLE_FIELDS = (
    "CERT",
    "REPDTE",
    "NAME",
    "ASSET",
    "DEP",
    "EQ",
    "NETINC",
    "ROA",
    "ROE",
)
FAILURE_FIELDS = (
    "CERT",
    "NAME",
    "FAILDATE",
    "FAILYR",
    "SAVR",
    "RESTYPE",
    "QBFDEP",
    "QBFASSET",
    "COST",
)


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def fetch_bytes(url: str, retries: int = 5) -> tuple[bytes | None, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,application/json,text/yaml,text/plain,*/*",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    last_error = ""
    last_status: int | None = None
    for attempt in range(1, retries + 1):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read()
                return body, {
                    "url": url,
                    "status": int(response.status),
                    "content_type": str(response.headers.get("Content-Type", "")),
                    "bytes": len(body),
                    "sha256": sha_bytes(body),
                    "attempt": attempt,
                    "seconds": round(time.monotonic() - started, 3),
                }
        except urllib.error.HTTPError as exc:
            last_status = int(exc.code)
            last_error = f"HTTPError {exc.code}: {exc.reason}"
            delay = min(3.0 * attempt, 12.0) if exc.code in {403, 429} else min(2 ** (attempt - 1), 8.0)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 ** (attempt - 1), 8.0))
    return None, {
        "url": url,
        "status": last_status,
        "error": last_error or "request failed",
        "attempts": retries,
    }


def taxonomy_fields(raw: bytes) -> dict[str, dict[str, Any]]:
    value = yaml.safe_load(raw.decode("utf-8"))
    candidates = [
        value,
        value.get("properties", {}) if isinstance(value, dict) else {},
    ]
    for candidate in list(candidates):
        if isinstance(candidate, dict):
            candidates.extend(
                item for item in candidate.values() if isinstance(item, dict)
            )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        properties = candidate.get("properties")
        if isinstance(properties, dict) and properties:
            if all(isinstance(item, dict) for item in properties.values()):
                return {str(key): dict(item) for key, item in properties.items()}
    raise ValueError("taxonomy properties not found")


def csv_frame(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8-sig", errors="strict")
    if text.lstrip().startswith("{"):
        raise ValueError("API returned JSON instead of CSV")
    frame = pd.read_csv(io.StringIO(text), low_memory=False)
    if frame.empty:
        raise ValueError("CSV contains no records")
    return frame


def financial_url(date: str, compact: bool) -> str:
    compact_date = date.replace("-", "")
    filter_value = (
        f"REPDTE:{compact_date}"
        if compact
        else f'REPDTE:["{date}" TO "{date}"]'
    )
    query = urllib.parse.urlencode(
        {
            "filters": filter_value,
            "fields": ",".join(SAMPLE_FIELDS),
            "sort_by": "CERT",
            "sort_order": "ASC",
            "limit": "10000",
            "offset": "0",
            "format": "csv",
            "download": "false",
            "filename": "data_file",
        }
    )
    return f"{API_BASE}/financials?{query}"


def failure_url() -> str:
    query = urllib.parse.urlencode(
        {
            "fields": ",".join(FAILURE_FIELDS),
            "sort_by": "FAILDATE",
            "sort_order": "ASC",
            "limit": "10000",
            "offset": "0",
            "format": "csv",
            "download": "false",
            "filename": "data_file",
        }
    )
    return f"{API_BASE}/failures?{query}"


def discover_feature_fields(properties: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    keywords = (
        "capital",
        "equity",
        "noncurrent",
        "past due",
        "charge-off",
        "charge off",
        "loan loss",
        "allowance",
        "return on assets",
        "return on equity",
        "net income",
        "liquidity",
        "deposit",
        "brokered",
        "asset growth",
        "loan growth",
    )
    output: list[dict[str, str]] = []
    for name, details in sorted(properties.items()):
        title = str(details.get("title", ""))
        description = str(details.get("description", ""))
        haystack = f"{title} {description}".lower()
        if any(keyword in haystack for keyword in keywords):
            output.append(
                {
                    "name": name,
                    "title": title,
                    "description": description[:500],
                    "type": str(details.get("type", "")),
                }
            )
    return output


def audit(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    acquisitions: list[dict[str, Any]] = []

    taxonomies: dict[str, dict[str, dict[str, Any]]] = {}
    for name, url in (
        ("financial", FINANCIAL_TAXONOMY),
        ("failure", FAILURE_TAXONOMY),
    ):
        raw, record = fetch_bytes(url)
        record["resource"] = f"{name}_taxonomy"
        acquisitions.append(record)
        if raw is None:
            continue
        path = output / f"{name}_taxonomy.yaml"
        path.write_bytes(raw)
        record["file"] = path.name
        try:
            taxonomies[name] = taxonomy_fields(raw)
            record["field_count"] = len(taxonomies[name])
        except (UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
            record["parse_error"] = f"{type(exc).__name__}: {exc}"

    failures = pd.DataFrame()
    raw_failures, failure_record = fetch_bytes(failure_url())
    failure_record["resource"] = "failures"
    acquisitions.append(failure_record)
    if raw_failures is not None:
        failure_path = output / "failures.csv"
        failure_path.write_bytes(raw_failures)
        failure_record["file"] = failure_path.name
        try:
            failures = csv_frame(raw_failures)
            failure_record["rows"] = len(failures)
        except (UnicodeDecodeError, ValueError, pd.errors.ParserError) as exc:
            failure_record["parse_error"] = f"{type(exc).__name__}: {exc}"

    samples: dict[str, pd.DataFrame] = {}
    sample_records: list[dict[str, Any]] = []
    for date in SAMPLE_DATES:
        selected_frame: pd.DataFrame | None = None
        attempts: list[dict[str, Any]] = []
        selected_raw: bytes | None = None
        for compact in (True, False):
            raw, record = fetch_bytes(financial_url(date, compact))
            record["filter_variant"] = "compact" if compact else "date_range"
            attempts.append(record)
            if raw is None:
                continue
            try:
                frame = csv_frame(raw)
            except (UnicodeDecodeError, ValueError, pd.errors.ParserError) as exc:
                record["parse_error"] = f"{type(exc).__name__}: {exc}"
                continue
            if {"CERT", "REPDTE"}.issubset(frame.columns):
                selected_frame = frame
                selected_raw = raw
                break
        summary: dict[str, Any] = {"date": date, "attempts": attempts}
        if selected_frame is not None and selected_raw is not None:
            path = output / f"financials_{date}.csv"
            path.write_bytes(selected_raw)
            samples[date] = selected_frame
            summary.update(
                {
                    "status": "ACQUIRED",
                    "file": path.name,
                    "rows": len(selected_frame),
                    "columns": list(selected_frame.columns),
                    "sha256": sha_file(path),
                    "duplicate_bank_quarters": int(
                        selected_frame.duplicated(["CERT", "REPDTE"]).sum()
                    ),
                }
            )
        else:
            summary["status"] = "FAILED"
        sample_records.append(summary)

    financial_properties = taxonomies.get("financial", {})
    failure_properties = taxonomies.get("failure", {})
    known_financial_fields = set(financial_properties)
    known_failure_fields = set(failure_properties)
    stable_fields = sorted(
        set.intersection(*(set(frame.columns) for frame in samples.values()))
        if samples
        else set()
    )
    non_null_rates: dict[str, dict[str, float]] = {}
    for date, frame in samples.items():
        non_null_rates[date] = {
            field: float(frame[field].notna().mean())
            for field in SAMPLE_FIELDS
            if field in frame.columns
        }

    failure_counts: dict[str, int] = {}
    window_counts: dict[str, int] = {}
    failure_date_parse_rate = 0.0
    if not failures.empty:
        years = pd.to_numeric(failures.get("FAILYR"), errors="coerce")
        if years.isna().all() and "FAILDATE" in failures:
            parsed = pd.to_datetime(failures["FAILDATE"], errors="coerce")
            years = parsed.dt.year
        failure_counts = {
            str(int(year)): int(count)
            for year, count in years.dropna().astype(int).value_counts().sort_index().items()
        }
        parsed_dates = pd.to_datetime(failures.get("FAILDATE"), errors="coerce")
        failure_date_parse_rate = float(parsed_dates.notna().mean())
        windows = {
            "train_1992_2004": (1992, 2004),
            "validation_2005_2008": (2005, 2008),
            "test_2009_2013": (2009, 2013),
            "postcrisis_2014_2025": (2014, 2025),
        }
        for name, (start, end) in windows.items():
            window_counts[name] = int(((years >= start) & (years <= end)).sum())

    checks = {
        "financial_taxonomy_acquired": bool(financial_properties),
        "failure_taxonomy_acquired": bool(failure_properties),
        "sample_fields_exist_in_financial_taxonomy": set(SAMPLE_FIELDS).issubset(
            known_financial_fields
        ),
        "failure_fields_exist_in_failure_taxonomy": set(FAILURE_FIELDS).issubset(
            known_failure_fields
        ),
        "failure_list_acquired": len(failures) >= 500,
        "failure_dates_parse_at_least_99pct": failure_date_parse_rate >= 0.99,
        "all_representative_quarters_acquired": len(samples) == len(SAMPLE_DATES),
        "all_sample_fields_stable": set(SAMPLE_FIELDS).issubset(stable_fields),
        "zero_sample_bank_quarter_duplicates": all(
            record.get("duplicate_bank_quarters") == 0
            for record in sample_records
            if record.get("status") == "ACQUIRED"
        ),
        "train_failures_at_least_20": window_counts.get("train_1992_2004", 0) >= 20,
        "validation_failures_at_least_20": window_counts.get(
            "validation_2005_2008", 0
        )
        >= 20,
        "test_failures_at_least_100": window_counts.get("test_2009_2013", 0)
        >= 100,
    }
    if all(checks.values()):
        recommendation = "PROCEED"
    elif checks["financial_taxonomy_acquired"] and checks["failure_list_acquired"]:
        recommendation = "REDESIGN"
    else:
        recommendation = "STOP"

    payload = {
        "schema": SCHEMA,
        "sources": {
            "api_base": API_BASE,
            "financial_taxonomy": FINANCIAL_TAXONOMY,
            "failure_taxonomy": FAILURE_TAXONOMY,
        },
        "acquisitions": acquisitions,
        "taxonomies": {
            "financial_field_count": len(financial_properties),
            "failure_field_count": len(failure_properties),
            "sample_fields": list(SAMPLE_FIELDS),
            "stable_sample_fields": stable_fields,
            "candidate_feature_fields": discover_feature_fields(
                financial_properties
            )[:200],
        },
        "financial_samples": sample_records,
        "sample_non_null_rates": non_null_rates,
        "failures": {
            "rows": int(len(failures)),
            "date_parse_rate": failure_date_parse_rate,
            "year_counts": failure_counts,
            "candidate_window_counts": window_counts,
        },
        "gate_checks": checks,
        "recommendation": recommendation,
        "status": f"STAGE0_{recommendation}",
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": "Access and label-feasibility audit only; no distress model evaluated.",
        },
    }
    payload_canonical = canonical(payload)
    return {
        "payload": payload,
        "payload_canonical": payload_canonical,
        "sha256": hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.output_dir)
    path = args.output_dir / "report.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    payload = report["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "recommendation": payload["recommendation"],
                "failure_rows": payload["failures"]["rows"],
                "candidate_windows": payload["failures"][
                    "candidate_window_counts"
                ],
                "quarters_acquired": sum(
                    item["status"] == "ACQUIRED"
                    for item in payload["financial_samples"]
                ),
                "report_sha256": report["sha256"],
                "absolute_score": payload["absolute_score"]["after"],
            },
            sort_keys=True,
        )
    )
    if payload["recommendation"] == "STOP":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
