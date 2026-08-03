from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .constants import FETCH_RETRIES, SEC_BASE, SEC_USER_AGENT
from .utils import sha256_file


def fetch_companyfacts(
    company: Mapping[str, str],
    cache_dir: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{company['ticker'].replace('.', '_')}.json"
    url = SEC_BASE.format(cik=company["cik"])

    if target.exists():
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
            return value, {
                "ticker": company["ticker"],
                "status": "CACHE",
                "url": url,
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        except (OSError, json.JSONDecodeError):
            target.unlink(missing_ok=True)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "identity",
            "Accept": "application/json",
        },
    )
    last_error = ""
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read()
            value = json.loads(data.decode("utf-8"))
            target.write_text(
                json.dumps(value, sort_keys=True),
                encoding="utf-8",
            )
            return value, {
                "ticker": company["ticker"],
                "status": "FETCHED",
                "url": url,
                "bytes": len(data),
                "sha256": sha256_file(target),
                "attempt": attempt,
            }
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 ** (attempt - 1), 8))

    return None, {
        "ticker": company["ticker"],
        "status": "FAILED",
        "url": url,
        "error": last_error,
    }
