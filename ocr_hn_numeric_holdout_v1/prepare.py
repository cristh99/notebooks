"""Prepare and seal an OCR-independent Honduran numeric holdout."""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .core import (
    SCHEMA_MANIFEST,
    canonical_json,
    deterministic_key,
    extract_digit_runs,
    extract_record_documents,
    sha256_bytes,
    stable_manifest,
)

API_URL = "https://contratacionesabiertas.gob.hn/api/v1/record/"
SELECTION_SALT = "ocr-hn-numeric-holdout-v2-20260804"


def session() -> requests.Session:
    client = requests.Session()
    retry = Retry(
        total=4, connect=4, read=4, status=4, backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}), respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    client.mount("https://", adapter); client.mount("http://", adapter)
    client.headers.update({
        "User-Agent": "OCR-HN-Numeric-Holdout/2.0 zero-cost public-research",
        "Accept": "application/json,application/pdf;q=0.9,*/*;q=0.1",
    })
    return client


def fetch_json(client: requests.Session, page: int, timeout: float) -> Mapping[str, Any]:
    response = client.get(API_URL, params={"page": page, "format": "json"}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise TypeError("record API did not return an object")
    return payload


def fetch_pdf(client: requests.Session, url: str, *, timeout: float, maximum_bytes: int):
    started = time.perf_counter()
    try:
        response = client.get(url, timeout=timeout, stream=True, allow_redirects=True)
        response.raise_for_status()
        declared = int(response.headers.get("content-length") or 0)
        if declared and declared > maximum_bytes:
            return None, {"status": "TOO_LARGE_DECLARED", "declared_bytes": declared}
        chunks, size = [], 0
        for chunk in response.iter_content(1024 * 1024):
            if not chunk: continue
            size += len(chunk)
            if size > maximum_bytes:
                return None, {"status": "TOO_LARGE_STREAM", "bytes": size}
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data.startswith(b"%PDF"):
            return None, {"status": "NOT_PDF", "bytes": len(data), "content_type": response.headers.get("content-type")}
        return data, {
            "status": "OK", "bytes": len(data), "final_url": response.url,
            "content_type": response.headers.get("content-type"),
            "elapsed_seconds": time.perf_counter() - started,
        }
    except Exception as exc:
        return None, {"status": "FETCH_ERROR", "error": f"{type(exc).__name__}: {exc}"}


def page_records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    package = payload.get("recordPackage") or {}
    rows = (package.get("records") or []) if isinstance(package, Mapping) else []
    return [row for row in rows if isinstance(row, Mapping)]


def collect_metadata(client, args, failures):
    documents, source_log, api_pages = [], [], []
    seen_urls, seen_records = set(), set()
    target_pool = max(args.target_units * args.candidate_pool_multiplier, 300)
    target_institutions = max(args.minimum_institutions * 3, args.minimum_institutions)
    failed = empty = duplicate_streak = 0
    for api_page in range(args.start_page, args.start_page + args.maximum_api_pages):
        try:
            payload = fetch_json(client, api_page, args.api_timeout)
        except Exception as exc:
            failures["API_FETCH_ERROR"] += 1; failed += 1
            source_log.append({"api_page": api_page, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
            if failed >= args.maximum_consecutive_api_failures: break
            continue
        failed = 0; api_pages.append(api_page)
        rows = page_records(payload); empty = 0 if rows else empty + 1
        record_ids = {
            str(row.get("ocid") or (row.get("compiledRelease") or {}).get("ocid") or "")
            for row in rows
        } - {""}
        duplicate = bool(record_ids and record_ids <= seen_records)
        seen_records.update(record_ids)
        page_docs = [doc for record in rows for doc in extract_record_documents(record, api_page)]
        added = 0
        for source in page_docs:
            if source["url"] in seen_urls: continue
            seen_urls.add(source["url"]); source = dict(source)
            source["metadata_selector_key"] = deterministic_key(
                SELECTION_SALT, "document", source.get("ocid") or "", source["url"]
            )
            documents.append(source); added += 1
        duplicate_streak = duplicate_streak + 1 if duplicate and added == 0 else 0
        institutions = len({row["institution"] for row in documents})
        source_log.append({
            "api_page": api_page, "status": "OK", "records": len(rows),
            "documents_seen": len(page_docs), "documents_added": added,
            "candidate_documents_total": len(documents),
            "candidate_institutions_total": institutions,
            "duplicate_record_page": duplicate, "consecutive_empty_pages": empty,
        })
        print(json.dumps({"phase":"metadata","api_page":api_page,"candidate_documents":len(documents),"candidate_institutions":institutions,"target_pool":target_pool}, ensure_ascii=False), flush=True)
        if len(documents) >= target_pool and institutions >= target_institutions: break
        if empty >= args.maximum_consecutive_empty_api_pages: break
        if duplicate_streak >= args.maximum_consecutive_empty_api_pages:
            failures["DUPLICATE_API_PAGE"] += duplicate_streak; break
    return documents, source_log, api_pages


def build_ocid_units(documents: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped = defaultdict(list)
    for source in documents:
        ocid = str(source.get("ocid") or "").strip()
        grouped[ocid or f"URL-{deterministic_key(source['url'])[:24]}"].append(dict(source))
    units = []
    for unit_id, candidates in grouped.items():
        candidates.sort(key=lambda row: (int(row.get("document_type_priority", 9)), str(row["metadata_selector_key"])))
        units.append({
            "unit_id": unit_id, "ocid": str(candidates[0].get("ocid") or ""),
            "institution": str(candidates[0]["institution"]),
            "unit_selector_key": deterministic_key(SELECTION_SALT, "unit", unit_id),
            "document_candidates": candidates,
        })
    return units


def round_robin_units(units: Iterable[Mapping[str, Any]]) -> Iterator[dict[str, Any]]:
    grouped = defaultdict(list)
    for unit in units: grouped[str(unit["institution"])].append(dict(unit))
    for rows in grouped.values(): rows.sort(key=lambda row: str(row["unit_selector_key"]))
    institutions = sorted(grouped, key=lambda name: deterministic_key(SELECTION_SALT, "institution", name))
    for offset in range(max((len(rows) for rows in grouped.values()), default=0)):
        for institution in institutions:
            if offset < len(grouped[institution]): yield grouped[institution][offset]


def choose_run(runs, digest, truth_counts, maximum_truth_occurrences):
    for run in sorted(runs, key=lambda row: row.selector_key(digest)):
        if truth_counts[run.truth] < maximum_truth_occurrences: return run
    return None


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    if args.target_crops != args.target_documents:
        raise ValueError("v2 requires target-crops == target-documents")
    args.target_units = args.target_crops
    client, failures = session(), Counter()
    metadata, source_log, api_pages = collect_metadata(client, args, failures)
    units = build_ocid_units(metadata)
    documents, crops = [], []
    institution_units, truth_counts = Counter(), Counter()
    institution_cap = max(5, math.ceil(min(args.target_units * args.maximum_institution_share, args.target_units / max(args.minimum_institutions,1) * 1.5)))
    truth_cap = max(3, math.ceil(args.target_units * args.maximum_truth_share))
    cache_dir = args.output_dir / "pdfs"; cache_dir.mkdir(parents=True, exist_ok=True)
    attempted_units = attempted_documents = 0
    for unit in round_robin_units(units):
        if len(crops) >= args.target_units: break
        institution = str(unit["institution"])
        if institution_units[institution] >= institution_cap:
            failures["INSTITUTION_UNIT_CAP"] += 1; continue
        attempted_units += 1; accepted = False
        for source in unit["document_candidates"][:args.maximum_documents_per_ocid]:
            attempted_documents += 1
            data, fetch = fetch_pdf(client, str(source["url"]), timeout=args.pdf_timeout, maximum_bytes=args.maximum_pdf_bytes)
            if data is None:
                failures[str(fetch.get("status") or "FETCH_FAILED")] += 1; continue
            digest = sha256_bytes(data)
            try:
                runs, extraction = extract_digit_runs(
                    data, maximum_pages=args.maximum_pages_per_document,
                    minimum_length=args.minimum_digits, maximum_length=args.maximum_digits,
                    minimum_distinct_digits=args.minimum_distinct_digits,
                    minimum_font_size=args.minimum_font_size,
                    maximum_full_page_image_coverage=args.maximum_image_coverage,
                )
            except Exception:
                failures["PDF_PARSE_ERROR"] += 1; continue
            run = choose_run(runs, digest, truth_counts, truth_cap)
            if run is None:
                failures[f"NO_ELIGIBLE_RUNS_{extraction.get('reason','UNKNOWN')}"] += 1; continue
            cache_filename = f"{digest}.pdf"; cache_path = cache_dir / cache_filename
            if not cache_path.exists(): cache_path.write_bytes(data)
            index = len(documents)
            documents.append({
                **source, "unit_id": unit["unit_id"], "unit_selector_key": unit["unit_selector_key"],
                "document_index": index, "source_sha256": digest, "source_bytes": len(data),
                "cache_filename": cache_filename, "fetch": fetch,
                "pdf_pages": extraction.get("pages"), "eligible_digit_runs": len(runs), "selected_crops": 1,
            })
            crop = {
                "unit_id": unit["unit_id"], "document_index": index, "source_sha256": digest,
                "url": source["url"], "ocid": source["ocid"], "institution": institution,
                "document_type": source["document_type"], "page_index": run.page_index,
                "bbox_pdf": [round(value,4) for value in run.bbox], "truth": run.truth,
                "font_name": run.font_name, "font_size": round(run.font_size,4),
                "span_flags": run.span_flags, "selector_key": run.selector_key(digest),
            }
            crop["crop_id"] = sha256_bytes(canonical_json(crop).encode("utf-8"))[:24]
            crops.append(crop); institution_units[institution] += 1; truth_counts[run.truth] += 1
            accepted = True; break
        if not accepted: failures["UNIT_WITHOUT_ELIGIBLE_DOCUMENT"] += 1
        if accepted or attempted_units % 10 == 0:
            print(json.dumps({"phase":"documents","attempted_units":attempted_units,"attempted_documents":attempted_documents,"accepted_units":len(crops),"institutions":len(institution_units),"latest_unit_accepted":accepted,"failures":dict(failures.most_common(8))}, ensure_ascii=False), flush=True)
    complete = (
        len(crops) == args.target_units == len(documents)
        and len({row["unit_id"] for row in crops}) == args.target_units
        and len(institution_units) >= args.minimum_institutions
    )
    payload = {
        "schema": SCHEMA_MANIFEST,
        "source": {
            "api": API_URL, "api_pages": api_pages, "api_page_log": source_log,
            "public_data_license": "CC BY 4.0 as declared by ONCAE/OCDS portal",
            "candidate_documents": len(metadata), "candidate_units": len(units),
        },
        "selection_policy": {
            "selection_salt": SELECTION_SALT, "ocr_used_for_selection": False,
            "sampling_unit": "one unique OCDS OCID", "documents_per_unit": 1, "crops_per_unit": 1,
            "ground_truth": "contiguous digit characters and exact coordinates from vector PDF text",
            "full_page_image_exclusion_threshold": args.maximum_image_coverage,
            "minimum_digits": args.minimum_digits, "maximum_digits": args.maximum_digits,
            "minimum_distinct_digits": args.minimum_distinct_digits, "minimum_font_size": args.minimum_font_size,
            "maximum_pages_per_document": args.maximum_pages_per_document,
            "maximum_documents_attempted_per_ocid": args.maximum_documents_per_ocid,
            "maximum_institution_share": args.maximum_institution_share,
            "maximum_units_per_institution": institution_cap,
            "maximum_truth_share": args.maximum_truth_share,
            "maximum_occurrences_of_one_truth": truth_cap,
            "unit_order": "institution-balanced deterministic round-robin; SHA-256 within institution",
            "crop_order": "SHA-256 selector independent of OCR output",
        },
        "targets": {"units":args.target_units,"crops":args.target_units,"documents":args.target_units,"minimum_institutions":args.minimum_institutions},
        "summary": {
            "complete": complete, "units": len(crops), "crops": len(crops), "documents": len(documents),
            "unique_ocids": len({row["unit_id"] for row in crops}), "institutions": len(institution_units),
            "institution_units": dict(sorted(institution_units.items())),
            "truth_frequency": dict(sorted(truth_counts.items())),
            "attempted_units": attempted_units, "attempted_documents": attempted_documents,
            "failures": dict(sorted(failures.items())),
        },
        "documents": documents, "crops": crops,
        "constraints": {"external_spend_usd":0,"gcloud_used":False,"gpu_used":False,"paid_api_used":False,"production_changed":False},
    }
    return stable_manifest(payload)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, default=Path("ocr_hn_numeric_holdout_v1/run/preparation"))
    p.add_argument("--target-crops", type=int, default=120); p.add_argument("--target-documents", type=int, default=120)
    p.add_argument("--minimum-institutions", type=int, default=8); p.add_argument("--start-page", type=int, default=1)
    p.add_argument("--maximum-api-pages", type=int, default=150); p.add_argument("--candidate-pool-multiplier", type=int, default=6)
    p.add_argument("--maximum-consecutive-api-failures", type=int, default=8); p.add_argument("--maximum-consecutive-empty-api-pages", type=int, default=3)
    p.add_argument("--maximum-pages-per-document", type=int, default=15); p.add_argument("--maximum-documents-per-ocid", type=int, default=3)
    p.add_argument("--minimum-digits", type=int, default=4); p.add_argument("--maximum-digits", type=int, default=12)
    p.add_argument("--minimum-distinct-digits", type=int, default=2); p.add_argument("--minimum-font-size", type=float, default=7.0)
    p.add_argument("--maximum-image-coverage", type=float, default=.55); p.add_argument("--maximum-institution-share", type=float, default=.20)
    p.add_argument("--maximum-truth-share", type=float, default=.03); p.add_argument("--maximum-pdf-bytes", type=int, default=25_000_000)
    p.add_argument("--api-timeout", type=float, default=45.0); p.add_argument("--pdf-timeout", type=float, default=60.0)
    return p


def main() -> int:
    args = parser().parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    report = build_manifest(args); path = args.output_dir / "manifest.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (args.output_dir/"manifest.sha256").write_text(f"{sha256_bytes(path.read_bytes())}  manifest.json\n",encoding="utf-8")
    print(json.dumps({"manifest":str(path),"summary":report["summary"],"manifest_sha256":report["manifest_sha256"]},ensure_ascii=False,indent=2))
    return 0 if report["summary"]["complete"] else 2


if __name__ == "__main__": raise SystemExit(main())
