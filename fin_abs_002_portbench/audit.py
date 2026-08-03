from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA = "fin-abs-002/portbench-data-audit/1"
SOURCE_COMMIT = "5e7cce2e1214a5dd026578c8814953f358b5a475"
EXPECTED_DATASET_SHA256 = (
    "495659fb40690d48748dcbcbd8c8c2add5371fac9d5be535270959ae8f519221"
)
EXPECTED_START = "2015-01-02"
EXPECTED_END = "2025-12-31"
EXPECTED_CLASSES = {
    "equities",
    "bonds",
    "commodities",
    "real_estate",
    "cryptocurrency",
    "cash",
}


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def asset_prefix(return_column: str) -> str:
    if not return_column.endswith("_return"):
        raise ValueError(f"not a return column: {return_column}")
    return return_column[: -len("_return")]


def asset_class(prefix: str) -> str:
    if prefix.startswith("real_estate_"):
        return "real_estate"
    return prefix.split("_", 1)[0]


def expected_split(dates: pd.Series) -> pd.Series:
    years = dates.dt.year
    return pd.Series(
        np.select(
            [years <= 2022, years == 2023, years >= 2024],
            ["train", "val", "test"],
            default="invalid",
        ),
        index=dates.index,
        dtype="object",
    )


def normalize_split(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip().lower()
    aliases = {
        "train": "train",
        "training": "train",
        "val": "val",
        "valid": "val",
        "validation": "val",
        "test": "test",
        "testing": "test",
    }
    return aliases.get(text, text)


def split_audit(frame: pd.DataFrame, dates: pd.Series) -> dict[str, Any]:
    columns = [
        column
        for column in frame.columns
        if column == "split" or column.endswith("_split")
    ]
    expected = expected_split(dates)
    details: list[dict[str, Any]] = []
    all_consistent = True
    for column in columns:
        normalized = frame[column].map(normalize_split)
        mask = normalized.notna()
        mismatches = int((normalized[mask] != expected[mask]).sum())
        all_consistent = all_consistent and mismatches == 0
        observed = {
            str(key): int(value)
            for key, value in normalized[mask].value_counts().sort_index().items()
        }
        details.append(
            {
                "column": column,
                "non_null": int(mask.sum()),
                "observed": observed,
                "mismatches": mismatches,
            }
        )
    return {
        "embedded_columns": columns,
        "embedded_column_count": len(columns),
        "embedded_labels_consistent": all_consistent,
        "details": details,
        "pinned_date_contract": {
            "train": "2015-01-02/2022-12-31",
            "val": "2023-01-01/2023-12-31",
            "test": "2024-01-01/2025-12-31",
        },
        "date_contract_counts": {
            str(key): int(value)
            for key, value in expected.value_counts().sort_index().items()
        },
    }


def return_convention_audit(
    frame: pd.DataFrame,
    tradable_return_columns: list[str],
    sample_limit: int = 30,
) -> dict[str, Any]:
    log_errors: list[float] = []
    simple_errors: list[float] = []
    per_asset: list[dict[str, Any]] = []
    for return_column in tradable_return_columns[:sample_limit]:
        prefix = asset_prefix(return_column)
        close_column = f"{prefix}_close"
        returns = pd.to_numeric(frame[return_column], errors="coerce")
        closes = pd.to_numeric(frame[close_column], errors="coerce")
        prior = closes.shift(1)
        valid = (
            returns.notna()
            & closes.notna()
            & prior.notna()
            & (closes > 0)
            & (prior > 0)
        )
        if int(valid.sum()) < 100:
            continue
        observed = returns[valid].to_numpy(dtype=float)
        simple = (closes[valid] / prior[valid] - 1.0).to_numpy(dtype=float)
        log = np.log(closes[valid] / prior[valid]).to_numpy(dtype=float)
        simple_error = float(np.nanmedian(np.abs(observed - simple)))
        log_error = float(np.nanmedian(np.abs(observed - log)))
        simple_errors.append(simple_error)
        log_errors.append(log_error)
        per_asset.append(
            {
                "asset": prefix,
                "observations": int(valid.sum()),
                "median_abs_error_simple": simple_error,
                "median_abs_error_log": log_error,
            }
        )
    aggregate_simple = (
        float(np.nanmedian(simple_errors)) if simple_errors else None
    )
    aggregate_log = float(np.nanmedian(log_errors)) if log_errors else None
    convention = "unknown"
    if aggregate_simple is not None and aggregate_log is not None:
        if aggregate_log < aggregate_simple:
            convention = "log_return"
        elif aggregate_simple < aggregate_log:
            convention = "simple_return"
        else:
            convention = "indistinguishable"
    return {
        "sampled_assets": len(per_asset),
        "median_abs_error_simple": aggregate_simple,
        "median_abs_error_log": aggregate_log,
        "inferred_convention": convention,
        "sample": per_asset[:10],
    }


def audit_dataset(path: Path) -> dict[str, Any]:
    dataset_sha = file_sha256(path)
    frame = pd.read_csv(path, low_memory=False)
    if "date" not in frame.columns:
        raise ValueError("PortBench dataset has no date column")
    dates = pd.to_datetime(frame["date"], errors="raise")
    if not dates.is_monotonic_increasing:
        raise ValueError("PortBench dates are not monotonic")
    if dates.duplicated().any():
        raise ValueError("PortBench dates are not unique")

    return_columns = sorted(
        column for column in frame.columns if column.endswith("_return")
    )
    tradable = sorted(
        column
        for column in return_columns
        if f"{asset_prefix(column)}_close" in frame.columns
    )
    classes = Counter(asset_class(asset_prefix(column)) for column in tradable)
    non_null = {
        asset_prefix(column): int(frame[column].notna().sum())
        for column in tradable
    }
    missingness = {
        "median_non_null_days": (
            float(np.median(list(non_null.values()))) if non_null else 0.0
        ),
        "minimum_non_null_days": min(non_null.values()) if non_null else 0,
        "maximum_non_null_days": max(non_null.values()) if non_null else 0,
        "assets_with_at_least_252_days": sum(
            value >= 252 for value in non_null.values()
        ),
        "assets_with_at_least_756_days": sum(
            value >= 756 for value in non_null.values()
        ),
    }
    splits = split_audit(frame, dates)
    convention = return_convention_audit(frame, tradable)

    checks = {
        "dataset_sha256_exact": dataset_sha == EXPECTED_DATASET_SHA256,
        "date_range_exact": (
            dates.iloc[0].date().isoformat() == EXPECTED_START
            and dates.iloc[-1].date().isoformat() == EXPECTED_END
        ),
        "row_count_at_least_4000": len(frame) >= 4000,
        "column_count_at_least_1000": len(frame.columns) >= 1000,
        "all_six_asset_classes_present": EXPECTED_CLASSES.issubset(classes),
        "tradable_assets_at_least_100": len(tradable) >= 100,
        "split_labels_consistent_if_present": splits[
            "embedded_labels_consistent"
        ],
        "return_convention_is_simple": convention["inferred_convention"]
        == "simple_return",
    }
    payload = {
        "schema": SCHEMA,
        "source": {
            "benchmark": "PortBench",
            "source_commit": SOURCE_COMMIT,
            "dataset": "AgenticFinLab/PortBench-Market",
            "file": "market-base-dataset.csv",
            "dataset_sha256": dataset_sha,
        },
        "shape": {
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "date_start": dates.iloc[0].date().isoformat(),
            "date_end": dates.iloc[-1].date().isoformat(),
        },
        "returns": {
            "all_return_columns": len(return_columns),
            "tradable_return_columns": len(tradable),
            "asset_class_counts": dict(sorted(classes.items())),
            "tradable_assets": [asset_prefix(column) for column in tradable],
            "missingness": missingness,
            "convention": convention,
        },
        "splits": splits,
        "gate_checks": checks,
        "status": "PASS_DATA_AUDIT" if all(checks.values()) else "OPEN_DATA_AUDIT",
        "score_effect": {
            "absolute_score_before": 423,
            "absolute_score_after": 423,
            "delta": 0,
            "reason": "Information acquisition only; no external performance gate has been run.",
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
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_dataset(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": report["payload"]["status"],
        "rows": report["payload"]["shape"]["rows"],
        "columns": report["payload"]["shape"]["columns"],
        "tradable_assets": report["payload"]["returns"][
            "tradable_return_columns"
        ],
        "classes": report["payload"]["returns"]["asset_class_counts"],
        "return_convention": report["payload"]["returns"]["convention"][
            "inferred_convention"
        ],
        "report_sha256": report["sha256"],
    }
    print(json.dumps(summary, sort_keys=True))
    if report["payload"]["status"] != "PASS_DATA_AUDIT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
