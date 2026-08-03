from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .constants import FETCH_RETRIES, SEC_USER_AGENT
from .utils import sha256_file

SEC_BULK_ARCHIVE = (
    "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
)


def _download_archive(target: Path) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and zipfile.is_zipfile(target):
        return {
            "status": "CACHE",
            "url": SEC_BULK_ARCHIVE,
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
        }
    target.unlink(missing_ok=True)
    request = urllib.request.Request(
        SEC_BULK_ARCHIVE,
        headers={
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "identity",
            "Accept": "application/zip",
        },
    )
    last_error = ""
    for attempt in range(1, FETCH_RETRIES + 1):
        temp = target.with_suffix(".zip.part")
        temp.unlink(missing_ok=True)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                with temp.open("wb") as handle:
                    shutil.copyfileobj(
                        response,
                        handle,
                        length=1024 * 1024,
                    )
            if not zipfile.is_zipfile(temp):
                raise zipfile.BadZipFile(
                    "SEC bulk response is not a ZIP archive"
                )
            temp.replace(target)
            return {
                "status": "FETCHED",
                "url": SEC_BULK_ARCHIVE,
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
                "attempt": attempt,
            }
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
            zipfile.BadZipFile,
        ) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            temp.unlink(missing_ok=True)
            time.sleep(min(2 ** (attempt - 1), 8))
    return {
        "status": "FAILED",
        "url": SEC_BULK_ARCHIVE,
        "error": last_error,
    }


def fetch_bulk_companyfacts(
    companies: Sequence[Mapping[str, str]],
    cache_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    archive_path = cache_dir / "companyfacts.zip"
    archive_record = _download_archive(archive_path)
    if archive_record["status"] == "FAILED":
        return {}, [
            {
                "ticker": company["ticker"],
                "status": "FAILED",
                "url": SEC_BULK_ARCHIVE,
                "error": archive_record.get(
                    "error",
                    "bulk download failed",
                ),
            }
            for company in companies
        ]

    values: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive_path) as archive:
        by_basename = {
            Path(name).name: name
            for name in archive.namelist()
            if name.lower().endswith(".json")
        }
        for company in companies:
            member_name = f"CIK{company['cik']}.json"
            member = by_basename.get(member_name)
            member_url = f"{SEC_BULK_ARCHIVE}#{member_name}"
            if member is None:
                records.append(
                    {
                        "ticker": company["ticker"],
                        "status": "FAILED",
                        "url": member_url,
                        "error": (
                            "member missing from official "
                            "bulk archive"
                        ),
                        "archive_sha256": archive_record[
                            "sha256"
                        ],
                    }
                )
                continue
            try:
                raw = archive.read(member)
                value = json.loads(raw.decode("utf-8"))
            except (
                KeyError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                records.append(
                    {
                        "ticker": company["ticker"],
                        "status": "FAILED",
                        "url": member_url,
                        "error": f"{type(exc).__name__}: {exc}",
                        "archive_sha256": archive_record[
                            "sha256"
                        ],
                    }
                )
                continue
            values[company["ticker"]] = value
            records.append(
                {
                    "ticker": company["ticker"],
                    "status": archive_record["status"],
                    "url": member_url,
                    "bytes": len(raw),
                    "archive_bytes": archive_record["bytes"],
                    "archive_sha256": archive_record[
                        "sha256"
                    ],
                    "member": member,
                }
            )
    return values, records
