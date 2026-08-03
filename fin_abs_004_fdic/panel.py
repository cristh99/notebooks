from __future__ import annotations

import argparse
import bisect
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

API_BASE = "https://banks.data.fdic.gov/api"
USER_AGENT = "FIN-ABS-004 academic benchmark contact: publicdatafeedback@fdic.gov"
PAGE_LIMIT = 10000
REQUEST_INTERVAL_SECONDS = 0.12
FETCH_RETRIES = 5
LABEL_HORIZON_DAYS = 730

RAW_FIELDS = (
    "CERT",
    "REPDTE",
    "NAME",
    "ASSET",
    "EQ",
    "DEP",
    "NETINC",
    "ROA",
    "ROE",
    "LNLSNET",
    "NCLNLSR",
    "NPERFV",
    "NTLNLSR",
    "NTRERESR",
    "NIM",
    "RBC1AAJ",
    "RBCRWAJ",
    "IDT1CER",
    "IDT1RWAJR",
    "LNATRESR",
    "COREDEP",
    "DEPUNINS",
    "FREPO",
    "SC",
    "ACTIVE",
    "BKCLASS",
    "STALP",
    "STNAME",
    "SPECGRPDESC",
)
FAILURE_FIELDS = (
    "CERT",
    "NAME",
    "FAILDATE",
    "FAILYR",
    "RESTYPE",
    "SAVR",
    "QBFDEP",
    "QBFASSET",
    "COST",
)
NUMERIC_RAW = tuple(
    field
    for field in RAW_FIELDS
    if field
    not in {
        "CERT",
        "REPDTE",
        "NAME",
        "BKCLASS",
        "STALP",
        "STNAME",
        "SPECGRPDESC",
    }
)
FEATURE_COLUMNS = (
    "log_assets",
    "equity_assets",
    "deposits_assets",
    "net_loans_assets",
    "noncurrent_loans_ratio",
    "nonperforming_assets_ratio",
    "nonperforming_loans_ratio",
    "net_chargeoff_proxy",
    "roa",
    "roe",
    "net_interest_margin",
    "rbc_capital_ratio",
    "rbc_risk_weighted_ratio",
    "tier1_common_ratio",
    "tier1_rwa_ratio",
    "loan_loss_reserve_ratio",
    "core_deposits_ratio",
    "uninsured_deposits_ratio",
    "wholesale_funding_assets",
    "securities_assets",
    "asset_growth_yoy",
    "deposit_growth_yoy",
    "equity_growth_yoy",
    "loan_growth_yoy",
    "roa_trailing_mean",
    "roa_trailing_std",
    "ncl_trailing_mean",
    "ncl_trailing_std",
    "negative_income",
    "declining_capital",
    "deposit_runoff",
    "absolute_asset_growth",
)
MONOTONIC_DIRECTIONS = {
    "log_assets": -1,
    "equity_assets": -1,
    "deposits_assets": -1,
    "net_loans_assets": 1,
    "noncurrent_loans_ratio": 1,
    "nonperforming_assets_ratio": 1,
    "nonperforming_loans_ratio": 1,
    "net_chargeoff_proxy": 1,
    "roa": -1,
    "roe": -1,
    "net_interest_margin": -1,
    "rbc_capital_ratio": -1,
    "rbc_risk_weighted_ratio": -1,
    "tier1_common_ratio": -1,
    "tier1_rwa_ratio": -1,
    "loan_loss_reserve_ratio": -1,
    "core_deposits_ratio": -1,
    "uninsured_deposits_ratio": 1,
    "wholesale_funding_assets": 1,
    "securities_assets": -1,
    "asset_growth_yoy": 1,
    "deposit_growth_yoy": -1,
    "equity_growth_yoy": -1,
    "loan_growth_yoy": 1,
    "roa_trailing_mean": -1,
    "roa_trailing_std": 1,
    "ncl_trailing_mean": 1,
    "ncl_trailing_std": 1,
    "negative_income": 1,
    "declining_capital": 1,
    "deposit_runoff": 1,
    "absolute_asset_growth": 1,
}

WINDOWS = {
    "train": (pd.Timestamp("1992-12-31"), pd.Timestamp("2002-12-31")),
    "validation": (pd.Timestamp("2005-03-31"), pd.Timestamp("2006-12-31")),
    "test": (pd.Timestamp("2009-03-31"), pd.Timestamp("2011-12-31")),
}
FETCH_RANGES = (
    (pd.Timestamp("1992-03-31"), pd.Timestamp("2002-12-31")),
    (pd.Timestamp("2004-03-31"), pd.Timestamp("2006-12-31")),
    (pd.Timestamp("2008-03-31"), pd.Timestamp("2011-12-31")),
)


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def quarter_ends(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    return list(pd.date_range(start=start, end=end, freq="QE-DEC"))


def acquisition_dates() -> list[pd.Timestamp]:
    output: list[pd.Timestamp] = []
    for start, end in FETCH_RANGES:
        output.extend(quarter_ends(start, end))
    return sorted(set(output))


def csv_url(endpoint: str, fields: Iterable[str], **parameters: Any) -> str:
    query = {
        "fields": ",".join(fields),
        "sort_by": parameters.pop("sort_by", "CERT"),
        "sort_order": "ASC",
        "limit": str(parameters.pop("limit", PAGE_LIMIT)),
        "offset": str(parameters.pop("offset", 0)),
        "format": "csv",
        "download": "false",
        "filename": "data_file",
        **{key: str(value) for key, value in parameters.items()},
    }
    return f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(query)}"


def fetch_bytes(url: str) -> tuple[bytes | None, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,*/*",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    last_error = ""
    last_status: int | None = None
    for attempt in range(1, FETCH_RETRIES + 1):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = response.read()
                return body, {
                    "url": url,
                    "status": int(response.status),
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "content_type": str(response.headers.get("Content-Type", "")),
                    "attempt": attempt,
                    "seconds": round(time.monotonic() - started, 3),
                }
        except urllib.error.HTTPError as exc:
            last_status = int(exc.code)
            last_error = f"HTTPError {exc.code}: {exc.reason}"
            delay = min(4.0 * attempt, 15.0) if exc.code in {403, 429} else min(2 ** (attempt - 1), 8.0)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 ** (attempt - 1), 8.0))
    return None, {
        "url": url,
        "status": last_status,
        "error": last_error or "request failed",
        "attempts": FETCH_RETRIES,
    }


def parse_csv(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8-sig", errors="strict")
    frame = pd.read_csv(io.StringIO(text), low_memory=False)
    return frame


def fetch_financial_quarter(
    date: pd.Timestamp,
    cache: Path,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    compact = date.strftime("%Y%m%d")
    pages: list[pd.DataFrame] = []
    records: list[dict[str, Any]] = []
    offset = 0
    for page_index in range(10):
        url = csv_url(
            "financials",
            RAW_FIELDS,
            filters=f"REPDTE:{compact}",
            offset=offset,
            limit=PAGE_LIMIT,
        )
        target = cache / f"financials_{compact}_{page_index:02d}.csv"
        if target.exists():
            raw = target.read_bytes()
            status = {
                "date": compact,
                "page": page_index,
                "offset": offset,
                "status": "CACHE",
                "file": target.name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "url": url,
            }
        else:
            raw, status = fetch_bytes(url)
            status.update({"date": compact, "page": page_index, "offset": offset})
            if raw is None:
                records.append(status)
                raise RuntimeError(f"FDIC financial acquisition failed for {compact}: {status}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            status.update({"status": "FETCHED", "file": target.name})
        frame = parse_csv(raw)
        status["rows"] = int(len(frame))
        records.append(status)
        if frame.empty:
            break
        pages.append(frame)
        if len(frame) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
        time.sleep(REQUEST_INTERVAL_SECONDS)
    if not pages:
        raise RuntimeError(f"no financial rows for {compact}")
    combined = pd.concat(pages, ignore_index=True)
    return combined, records


def fetch_failures(cache: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = csv_url("failures", FAILURE_FIELDS, sort_by="FAILDATE", limit=10000)
    target = cache / "failures.csv"
    if target.exists():
        raw = target.read_bytes()
        record = {
            "status": "CACHE",
            "url": url,
            "file": target.name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    else:
        raw, record = fetch_bytes(url)
        if raw is None:
            raise RuntimeError(f"FDIC failure acquisition failed: {record}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        record.update({"status": "FETCHED", "file": target.name})
    frame = parse_csv(raw)
    record["rows"] = int(len(frame))
    return frame, record


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = pd.to_numeric(denominator, errors="coerce")
    numerator = pd.to_numeric(numerator, errors="coerce")
    return numerator.where(denominator > 0) / denominator.where(denominator > 0)


def add_features(panel: pd.DataFrame) -> pd.DataFrame:
    frame = panel.copy().sort_values(["CERT", "REPDTE"]).reset_index(drop=True)
    for column in NUMERIC_RAW:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["log_assets"] = np.log(frame["ASSET"].where(frame["ASSET"] > 0))
    frame["equity_assets"] = safe_ratio(frame["EQ"], frame["ASSET"])
    frame["deposits_assets"] = safe_ratio(frame["DEP"], frame["ASSET"])
    frame["net_loans_assets"] = safe_ratio(frame["LNLSNET"], frame["ASSET"])
    frame["noncurrent_loans_ratio"] = frame["NCLNLSR"]
    frame["nonperforming_assets_ratio"] = frame["NPERFV"]
    frame["nonperforming_loans_ratio"] = frame["NTLNLSR"]
    frame["net_chargeoff_proxy"] = frame["NTRERESR"]
    frame["roa"] = frame["ROA"]
    frame["roe"] = frame["ROE"]
    frame["net_interest_margin"] = frame["NIM"]
    frame["rbc_capital_ratio"] = frame["RBC1AAJ"]
    frame["rbc_risk_weighted_ratio"] = frame["RBCRWAJ"]
    frame["tier1_common_ratio"] = frame["IDT1CER"]
    frame["tier1_rwa_ratio"] = frame["IDT1RWAJR"]
    frame["loan_loss_reserve_ratio"] = frame["LNATRESR"]
    frame["core_deposits_ratio"] = safe_ratio(frame["COREDEP"], frame["DEP"])
    frame["uninsured_deposits_ratio"] = safe_ratio(frame["DEPUNINS"], frame["DEP"])
    frame["wholesale_funding_assets"] = safe_ratio(frame["FREPO"], frame["ASSET"])
    frame["securities_assets"] = safe_ratio(frame["SC"], frame["ASSET"])

    lagged = frame.groupby("CERT", sort=False)[["ASSET", "DEP", "EQ", "LNLSNET", "REPDTE"]].shift(4)
    date_gap = (frame["REPDTE"] - lagged["REPDTE"]).dt.days
    valid_gap = date_gap.between(330, 400)
    for raw, name in (
        ("ASSET", "asset_growth_yoy"),
        ("DEP", "deposit_growth_yoy"),
        ("EQ", "equity_growth_yoy"),
        ("LNLSNET", "loan_growth_yoy"),
    ):
        prior = lagged[raw]
        growth = safe_ratio(frame[raw], prior) - 1.0
        frame[name] = growth.where(valid_gap)
    frame["absolute_asset_growth"] = frame["asset_growth_yoy"].abs()
    frame["deposit_runoff"] = (-frame["deposit_growth_yoy"]).clip(lower=0)
    frame["negative_income"] = (frame["NETINC"] < 0).astype(float)
    frame["declining_capital"] = (-frame["equity_growth_yoy"]).clip(lower=0)

    grouped = frame.groupby("CERT", sort=False)
    frame["roa_trailing_mean"] = grouped["roa"].transform(
        lambda values: values.rolling(4, min_periods=2).mean()
    )
    frame["roa_trailing_std"] = grouped["roa"].transform(
        lambda values: values.rolling(4, min_periods=2).std()
    )
    frame["ncl_trailing_mean"] = grouped["noncurrent_loans_ratio"].transform(
        lambda values: values.rolling(4, min_periods=2).mean()
    )
    frame["ncl_trailing_std"] = grouped["noncurrent_loans_ratio"].transform(
        lambda values: values.rolling(4, min_periods=2).std()
    )
    return frame


def earliest_future_date(dates: list[pd.Timestamp], current: pd.Timestamp) -> pd.Timestamp | None:
    index = bisect.bisect_right(dates, current)
    return dates[index] if index < len(dates) else None


def add_labels(panel: pd.DataFrame, failures: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    failure_frame = failures.copy()
    failure_frame["CERT"] = pd.to_numeric(failure_frame["CERT"], errors="coerce").astype("Int64")
    failure_frame["FAILDATE"] = pd.to_datetime(failure_frame["FAILDATE"], errors="coerce")
    failure_frame["RESTYPE"] = failure_frame["RESTYPE"].astype(str).str.upper().str.strip()
    failures_only = failure_frame.loc[
        (failure_frame["RESTYPE"] == "FAILURE")
        & failure_frame["CERT"].notna()
        & failure_frame["FAILDATE"].notna()
    ]
    assistance = failure_frame.loc[
        (failure_frame["RESTYPE"] == "ASSISTANCE")
        & failure_frame["CERT"].notna()
        & failure_frame["FAILDATE"].notna()
    ]
    failure_dates: dict[int, list[pd.Timestamp]] = defaultdict(list)
    assistance_dates: dict[int, list[pd.Timestamp]] = defaultdict(list)
    for row in failures_only.itertuples(index=False):
        failure_dates[int(row.CERT)].append(pd.Timestamp(row.FAILDATE))
    for row in assistance.itertuples(index=False):
        assistance_dates[int(row.CERT)].append(pd.Timestamp(row.FAILDATE))
    for values in failure_dates.values():
        values.sort()
    for values in assistance_dates.values():
        values.sort()

    frame = panel.copy()
    labels: list[int] = []
    days: list[float] = []
    assistance_horizon: list[int] = []
    for row in frame.itertuples(index=False):
        cert = int(row.CERT)
        date = pd.Timestamp(row.REPDTE)
        future = earliest_future_date(failure_dates.get(cert, []), date)
        distance = (future - date).days if future is not None else None
        labels.append(int(distance is not None and 0 < distance <= LABEL_HORIZON_DAYS))
        days.append(float(distance) if distance is not None else np.nan)
        assist = earliest_future_date(assistance_dates.get(cert, []), date)
        assist_distance = (assist - date).days if assist is not None else None
        assistance_horizon.append(
            int(assist_distance is not None and 0 < assist_distance <= LABEL_HORIZON_DAYS)
        )
    frame["label"] = labels
    frame["days_to_failure"] = days
    frame["assistance_within_horizon"] = assistance_horizon
    report = {
        "failure_records_total": int(len(failure_frame)),
        "failure_records_labeled": int(len(failures_only)),
        "assistance_records_excluded": int(len(assistance)),
        "panel_positive_rows": int(frame["label"].sum()),
        "assistance_horizon_rows": int(frame["assistance_within_horizon"].sum()),
    }
    return frame, report


def assign_split(dates: pd.Series) -> pd.Series:
    output = pd.Series("gap", index=dates.index, dtype="object")
    for split, (start, end) in WINDOWS.items():
        output.loc[dates.between(start, end)] = split
    return output


def build_panel(cache: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    acquisitions: list[dict[str, Any]] = []
    quarters: list[pd.DataFrame] = []
    for index, date in enumerate(acquisition_dates()):
        frame, records = fetch_financial_quarter(date, cache)
        acquisitions.extend(records)
        quarters.append(frame)
        if index + 1 < len(acquisition_dates()):
            time.sleep(REQUEST_INTERVAL_SECONDS)
    financial = pd.concat(quarters, ignore_index=True)
    financial["CERT"] = pd.to_numeric(financial["CERT"], errors="coerce").astype("Int64")
    financial["REPDTE"] = pd.to_datetime(
        pd.to_numeric(financial["REPDTE"], errors="coerce").astype("Int64").astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    financial = financial.loc[
        financial["CERT"].notna()
        & financial["REPDTE"].notna()
        & pd.to_numeric(financial["ASSET"], errors="coerce").gt(0)
    ].copy()
    financial["CERT"] = financial["CERT"].astype(int)
    duplicates_before = int(financial.duplicated(["CERT", "REPDTE"]).sum())
    financial = financial.sort_values(["CERT", "REPDTE"]).drop_duplicates(
        ["CERT", "REPDTE"], keep="last"
    )
    failures, failure_record = fetch_failures(cache)
    acquisitions.append({"resource": "failures", **failure_record})

    featured = add_features(financial)
    labeled, label_report = add_labels(featured, failures)
    labeled["split"] = assign_split(labeled["REPDTE"])
    panel = labeled.loc[labeled["split"].isin(WINDOWS)].copy()
    feature_frame = panel[
        [
            "CERT",
            "REPDTE",
            "NAME",
            "BKCLASS",
            "STALP",
            "STNAME",
            "SPECGRPDESC",
            "split",
            "label",
            "days_to_failure",
            "assistance_within_horizon",
            "ASSET",
            *FEATURE_COLUMNS,
        ]
    ].copy()
    feature_frame = feature_frame.sort_values(["split", "REPDTE", "CERT"])
    panel_path = output / "panel_features.csv"
    feature_frame.to_csv(panel_path, index=False, float_format="%.17g")

    split_counts = {
        split: {
            "rows": int(len(group)),
            "entities": int(group["CERT"].nunique()),
            "positives": int(group["label"].sum()),
            "positive_entities": int(group.loc[group["label"] == 1, "CERT"].nunique()),
        }
        for split, group in feature_frame.groupby("split", sort=True)
    }
    payload = {
        "schema": "fin-abs-004/fdic-panel/1",
        "protocol": {
            "raw_fields": list(RAW_FIELDS),
            "feature_columns": list(FEATURE_COLUMNS),
            "monotonic_directions": MONOTONIC_DIRECTIONS,
            "label_horizon_days": LABEL_HORIZON_DAYS,
            "windows": {
                key: [start.date().isoformat(), end.date().isoformat()]
                for key, (start, end) in WINDOWS.items()
            },
        },
        "acquisition": {
            "quarters": len(acquisition_dates()),
            "records": acquisitions,
            "all_requests_successful": all(
                record.get("status") in {"FETCHED", "CACHE"}
                for record in acquisitions
            ),
        },
        "financial": {
            "raw_rows": int(sum(len(frame) for frame in quarters)),
            "deduplicated_rows": int(len(financial)),
            "duplicate_bank_quarters_before_dedup": duplicates_before,
            "date_start": financial["REPDTE"].min().date().isoformat(),
            "date_end": financial["REPDTE"].max().date().isoformat(),
        },
        "labels": label_report,
        "evaluation_panel": {
            "rows": int(len(feature_frame)),
            "split_counts": split_counts,
            "feature_file": panel_path.name,
            "feature_file_sha256": sha_file(panel_path),
            "panel_rows_sha256": digest(feature_frame.to_dict(orient="records")),
            "zero_bank_quarter_duplicates": int(
                feature_frame.duplicated(["CERT", "REPDTE"]).sum()
            )
            == 0,
        },
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": "Panel acquisition and labeling only; no distress model evaluated.",
        },
    }
    payload_canonical = canonical(payload)
    report = {
        "payload": payload,
        "payload_canonical": payload_canonical,
        "sha256": hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest(),
    }
    report_path = output / "panel_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_panel(args.cache, args.output_dir)
    payload = report["payload"]
    print(
        json.dumps(
            {
                "quarters": payload["acquisition"]["quarters"],
                "panel_rows": payload["evaluation_panel"]["rows"],
                "split_counts": payload["evaluation_panel"]["split_counts"],
                "panel_sha256": payload["evaluation_panel"]["feature_file_sha256"],
                "report_sha256": report["sha256"],
                "absolute_score": 423,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
