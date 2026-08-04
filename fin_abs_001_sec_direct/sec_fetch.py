from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from .constants import (
    FETCH_RETRIES,
    REQUEST_INTERVAL_SECONDS,
    SEC_BASE,
    SEC_USER_AGENT,
)
from .utils import sha256_file


def _decode_body(raw: bytes, content_encoding: str) -> bytes:
    encoding = content_encoding.lower().strip()
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def _load_cached_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return None
    return value if isinstance(value, dict) else None


def _fetch_companyfacts(
    company: Mapping[str, str],
    cache_dir: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    cik = str(company["cik"])
    ticker = str(company["ticker"])
    url = SEC_BASE.format(cik=cik)
    target = cache_dir / "companyfacts" / f"CIK{cik}.json"
    target.parent.mkdir(parents=True, exist_ok=True)

    cached = _load_cached_json(target)
    if cached is not None:
        return cached, {
            "ticker": ticker,
            "status": "CACHE",
            "url": url,
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
            "cik": cik,
        }

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
            "Host": "data.sec.gov",
            "Connection": "close",
        },
    )
    last_error = ""
    last_status: int | None = None
    for attempt in range(1, FETCH_RETRIES + 1):
        temp = target.with_suffix(".json.part")
        temp.unlink(missing_ok=True)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
                body = _decode_body(
                    raw,
                    str(response.headers.get("Content-Encoding", "")),
                )
                value = json.loads(body.decode("utf-8"))
                if not isinstance(value, dict) or "facts" not in value:
                    raise ValueError("SEC response is not Company Facts JSON")
                temp.write_bytes(body)
                temp.replace(target)
                return value, {
                    "ticker": ticker,
                    "status": "FETCHED",
                    "url": url,
                    "bytes": len(body),
                    "sha256": sha256_file(target),
                    "cik": cik,
                    "attempt": attempt,
                    "content_type": str(
                        response.headers.get("Content-Type", "")
                    ),
                }
        except urllib.error.HTTPError as exc:
            last_status = int(exc.code)
            last_error = f"HTTPError: HTTP Error {exc.code}: {exc.reason}"
            temp.unlink(missing_ok=True)
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else 0.0
            except (TypeError, ValueError):
                delay = 0.0
            if exc.code in {403, 429}:
                delay = max(delay, min(4.0 * attempt, 12.0))
            else:
                delay = max(delay, min(2 ** (attempt - 1), 8.0))
            time.sleep(delay)
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            gzip.BadGzipFile,
            zlib.error,
        ) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            temp.unlink(missing_ok=True)
            time.sleep(min(2 ** (attempt - 1), 8.0))

    return None, {
        "ticker": ticker,
        "status": "FAILED",
        "url": url,
        "cik": cik,
        "http_status": last_status,
        "error": last_error or "Company Facts download failed",
    }


def fetch_bulk_companyfacts(
    companies: Sequence[Mapping[str, str]],
    cache_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Fetch the frozen universe from the official per-company SEC API.

    The public bulk ZIP is efficient but can be blocked for shared cloud runner
    addresses. The documented Company Facts endpoint is still official SEC data,
    lets the benchmark download only the 50 required companies, and stays below
    the SEC fair-access ceiling through a deterministic request interval.

    The legacy function name is retained so the frozen benchmark entry point and
    downstream evidence contract do not change.
    """

    values: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    for index, company in enumerate(companies):
        value, record = _fetch_companyfacts(company, cache_dir)
        records.append(record)
        if value is not None:
            values[str(company["ticker"])] = value
        if index + 1 < len(companies) and record.get("status") != "CACHE":
            time.sleep(REQUEST_INTERVAL_SECONDS)
    return values, records
