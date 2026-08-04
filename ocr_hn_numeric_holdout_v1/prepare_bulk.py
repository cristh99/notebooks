"""Reliable bulk-source wrapper for the Honduran numeric OCR holdout.

The portal's paginated API can stall before its first response. This wrapper
keeps the frozen selection logic in :mod:`prepare` but supplies compiled ONCAE
releases from the Open Contracting Data Registry's small, line-delimited gzip
snapshots. Each JSON line remains one OCDS contracting process.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import prepare as legacy
from .core import deterministic_key, extract_record_documents, sha256_bytes, stable_manifest

REGISTRY_PUBLICATION = "https://data.open-contracting.org/en/publication/122"
DEFAULT_BULK_URLS = (
    "https://data.open-contracting.org/en/publication/122/download?name=2026.jsonl.gz",
    "https://data.open-contracting.org/en/publication/122/download?name=2025.jsonl.gz",
)


def session() -> requests.Session:
    client = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=1,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    client.mount("https://", adapter)
    client.mount("http://", adapter)
    client.headers.update(
        {
            "User-Agent": "OCR-HN-Numeric-Holdout/2.1 zero-cost public-research",
            "Accept": "application/json,application/gzip,application/pdf;q=0.9,*/*;q=0.1",
        }
    )
    return client


def download_bulk(client: requests.Session, url: str, path: Path, args: argparse.Namespace) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    digest = hashlib.sha256()
    size = 0
    try:
        with client.get(
            url,
            timeout=(args.bulk_connect_timeout, args.bulk_read_timeout),
            stream=True,
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            declared = int(response.headers.get("content-length") or 0)
            if declared and declared > args.maximum_bulk_bytes:
                return {"status": "TOO_LARGE_DECLARED", "url": url, "declared_bytes": declared}
            with path.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > args.maximum_bulk_bytes:
                        path.unlink(missing_ok=True)
                        return {"status": "TOO_LARGE_STREAM", "url": url, "bytes": size}
                    digest.update(chunk)
                    handle.write(chunk)
            return {
                "status": "OK",
                "url": url,
                "final_url": response.url,
                "bytes": size,
                "sha256": digest.hexdigest(),
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "content_type": response.headers.get("content-type"),
                "elapsed_seconds": time.perf_counter() - started,
                "cache_filename": path.name,
            }
    except Exception as exc:
        path.unlink(missing_ok=True)
        return {
            "status": "FETCH_ERROR",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": time.perf_counter() - started,
        }


def compiled_release(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
    nested = value.get("compiledRelease")
    if isinstance(nested, Mapping):
        return nested
    record = value.get("record")
    if isinstance(record, Mapping) and isinstance(record.get("compiledRelease"), Mapping):
        return record["compiledRelease"]
    if value.get("ocid") and any(key in value for key in ("tender", "awards", "contracts", "parties", "buyer")):
        return value
    return None


def collect_bulk_metadata(client: requests.Session, args: argparse.Namespace, failures):
    documents: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    units: set[str] = set()
    target_units = max(args.target_units * args.candidate_pool_multiplier, 300)
    target_institutions = max(args.minimum_institutions * 3, args.minimum_institutions)
    bulk_dir = args.output_dir / "bulk"

    for index, url in enumerate(tuple(args.bulk_url or DEFAULT_BULK_URLS)):
        path = bulk_dir / f"source-{index:02d}.jsonl.gz"
        source = download_bulk(client, url, path, args)
        if source["status"] != "OK":
            failures[f"BULK_{source['status']}"] += 1
            logs.append(source)
            continue
        scanned = seen = added = malformed = 0
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        malformed += 1
                        failures["BULK_MALFORMED_JSON_LINE"] += 1
                        continue
                    if not isinstance(value, Mapping):
                        malformed += 1
                        failures["BULK_NON_OBJECT_LINE"] += 1
                        continue
                    release = compiled_release(value)
                    if release is None:
                        failures["BULK_NO_COMPILED_RELEASE"] += 1
                        continue
                    scanned += 1
                    ocid = str(release.get("ocid") or value.get("ocid") or "")
                    rows = extract_record_documents(
                        {"ocid": ocid, "compiledRelease": release}, line_number
                    )
                    seen += len(rows)
                    for row in rows:
                        if row["url"] in seen_urls:
                            continue
                        seen_urls.add(row["url"])
                        row = dict(row)
                        row["bulk_source_index"] = index
                        row["bulk_line_number"] = line_number
                        row["metadata_selector_key"] = deterministic_key(
                            legacy.SELECTION_SALT,
                            "document",
                            row.get("ocid") or "",
                            row["url"],
                        )
                        documents.append(row)
                        added += 1
                        units.add(row.get("ocid") or f"URL-{deterministic_key(row['url'])[:24]}")
                    institutions = len({row["institution"] for row in documents})
                    if scanned % 1000 == 0:
                        print(
                            json.dumps(
                                {
                                    "phase": "bulk_metadata",
                                    "source": index,
                                    "records_scanned": scanned,
                                    "candidate_units": len(units),
                                    "candidate_documents": len(documents),
                                    "candidate_institutions": institutions,
                                    "target_unit_pool": target_units,
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                    if len(units) >= target_units and institutions >= target_institutions:
                        break
        except Exception as exc:
            failures["BULK_PARSE_ERROR"] += 1
            source["parse_error"] = f"{type(exc).__name__}: {exc}"
        source.update(
            {
                "records_scanned": scanned,
                "documents_seen": seen,
                "documents_added": added,
                "malformed_lines": malformed,
                "candidate_units_total": len(units),
                "candidate_documents_total": len(documents),
                "candidate_institutions_total": len({row["institution"] for row in documents}),
            }
        )
        logs.append(source)
        print(
            json.dumps(
                {
                    "phase": "bulk_source_complete",
                    "source": index,
                    "status": source["status"],
                    "records_scanned": scanned,
                    "candidate_units": len(units),
                    "candidate_documents": len(documents),
                    "candidate_institutions": source["candidate_institutions_total"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if len(units) >= target_units and source["candidate_institutions_total"] >= target_institutions:
            break
    return documents, logs, []


def parser() -> argparse.ArgumentParser:
    parser = legacy.parser()
    parser.add_argument("--bulk-url", action="append", default=[])
    parser.add_argument("--maximum-bulk-bytes", type=int, default=500_000_000)
    parser.add_argument("--bulk-connect-timeout", type=float, default=15.0)
    parser.add_argument("--bulk-read-timeout", type=float, default=120.0)
    return parser


def main() -> int:
    args = parser().parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    legacy.session = session
    legacy.collect_metadata = collect_bulk_metadata
    report = legacy.build_manifest(args)
    old_source = report.get("source") or {}
    report["source"] = {
        "registry_publication": REGISTRY_PUBLICATION,
        "registry_description": "OCP Data Registry compiled releases retrieved from ONCAE",
        "bulk_sources": old_source.get("api_page_log") or [],
        "public_data_license": "Creative Commons Attribution 4.0 International",
        "candidate_documents": old_source.get("candidate_documents"),
        "candidate_units": old_source.get("candidate_units"),
    }
    report = stable_manifest(report)
    path = args.output_dir / "manifest.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "manifest.sha256").write_text(
        f"{sha256_bytes(path.read_bytes())}  manifest.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest": str(path),
                "summary": report["summary"],
                "manifest_sha256": report["manifest_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["summary"]["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
