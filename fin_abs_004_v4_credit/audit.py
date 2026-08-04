from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "fin-abs-004/v4finbench-data-audit/1"
DATASET_HANDLE = "sebastiantomczak10/v4-group-corporate-bankruptcy"
PINNED_UPSTREAM_REPOSITORY = "leokeechye/V4FinBench"
PINNED_UPSTREAM_COMMIT = "908b88d373a76e0064329e38fc01cba98bebae5f"
ABSOLUTE_SCORE = 423

EXPECTED_FILES = (
    "company_years.parquet",
    "company_years_h1.parquet",
    "company_years_h2.parquet",
    "company_years_h3.parquet",
    "company_years_h4.parquet",
    "company_years_h5.parquet",
    "company_years_h6.parquet",
)
PRIMARY_TASK = "company_years_h2.parquet"
LABEL_COLUMN = "main_label"
GROUP_COLUMN = "company"
COUNTRY_COLUMN = "country"
YEAR_COLUMN = "year"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def dataset_version(path: Path) -> str | None:
    parts = path.resolve().parts
    for index, part in enumerate(parts[:-1]):
        if part == "versions" and index + 1 < len(parts):
            return parts[index + 1]
    match = re.search(r"(?:^|/)versions/([^/]+)", path.as_posix())
    return match.group(1) if match else None


def parquet_inventory(root: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    inventory: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.parquet")):
        parquet = pq.ParquetFile(path)
        names = parquet.schema_arrow.names
        inventory.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": parquet.metadata.num_rows,
                "row_groups": parquet.metadata.num_row_groups,
                "columns": len(names),
                "column_names": names,
            }
        )
    return inventory


def label_summary(path: Path) -> dict[str, Any]:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    if LABEL_COLUMN not in parquet.schema_arrow.names:
        return {
            "available": False,
            "rows": parquet.metadata.num_rows,
            "positive": None,
            "negative": None,
            "positive_rate": None,
            "nulls": None,
        }
    table = parquet.read(columns=[LABEL_COLUMN])
    values = table[LABEL_COLUMN]
    positive = int(pc.sum(pc.cast(values, "int64")).as_py() or 0)
    nulls = int(values.null_count)
    rows = len(values)
    negative = rows - positive - nulls
    return {
        "available": True,
        "rows": rows,
        "positive": positive,
        "negative": negative,
        "positive_rate": positive / rows if rows else None,
        "nulls": nulls,
    }


def distinct_count(path: Path, column: str) -> int | None:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    if column not in parquet.schema_arrow.names:
        return None
    table = parquet.read(columns=[column])
    return int(pc.count_distinct(table[column]).as_py())


def build_payload(
    *,
    resolved_path: Path,
    inventory: list[dict[str, Any]],
    label: Mapping[str, Any],
    group_count: int | None,
    country_count: int | None,
    year_count: int | None,
) -> dict[str, Any]:
    by_name = {item["name"]: item for item in inventory}
    primary = by_name.get(PRIMARY_TASK)
    primary_columns = set(primary["column_names"]) if primary else set()
    feature_count = (
        len(primary_columns - {LABEL_COLUMN, GROUP_COLUMN, COUNTRY_COLUMN, YEAR_COLUMN})
        if primary
        else 0
    )
    gates = {
        "dataset_handle_frozen": DATASET_HANDLE == "sebastiantomczak10/v4-group-corporate-bankruptcy",
        "upstream_commit_frozen": len(PINNED_UPSTREAM_COMMIT) == 40,
        "all_expected_files_present": set(EXPECTED_FILES).issubset(by_name),
        "exactly_seven_expected_parquet_files": len(inventory) == len(EXPECTED_FILES),
        "primary_task_present": primary is not None,
        "primary_rows_at_least_500k": bool(primary and primary["rows"] >= 500_000),
        "primary_columns_at_least_130": bool(primary and primary["columns"] >= 130),
        "feature_count_at_least_125": feature_count >= 125,
        "label_present": LABEL_COLUMN in primary_columns,
        "label_has_at_least_1000_positives": int(label.get("positive") or 0) >= 1_000,
        "label_has_no_nulls": label.get("nulls") == 0,
        "group_column_present": GROUP_COLUMN in primary_columns,
        "country_column_present": COUNTRY_COLUMN in primary_columns,
        "year_column_present": YEAR_COLUMN in primary_columns,
        "company_count_at_least_100k": int(group_count or 0) >= 100_000,
        "country_count_at_least_4": int(country_count or 0) >= 4,
        "year_count_at_least_10": int(year_count or 0) >= 10,
        "all_hashes_sha256": all(
            re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"])) is not None
            for item in inventory
        ),
        "no_data_embedded_in_report": True,
    }
    passed = all(gates.values())
    return {
        "schema": SCHEMA,
        "status": "PASS_DATA_AUDIT" if passed else "BLOCKED_DATA_AUDIT",
        "dataset": {
            "handle": DATASET_HANDLE,
            "resolved_path_name": resolved_path.name,
            "version": dataset_version(resolved_path),
            "license": "CC BY 4.0 (declared by upstream benchmark)",
            "inventory": inventory,
            "inventory_sha256": digest(inventory),
        },
        "upstream": {
            "repository": PINNED_UPSTREAM_REPOSITORY,
            "commit": PINNED_UPSTREAM_COMMIT,
        },
        "primary_task": {
            "file": PRIMARY_TASK,
            "label_column": LABEL_COLUMN,
            "group_column": GROUP_COLUMN,
            "country_column": COUNTRY_COLUMN,
            "year_column": YEAR_COLUMN,
            "feature_count_excluding_four_control_columns": feature_count,
            "label_summary": dict(label),
            "distinct_companies": group_count,
            "distinct_countries": country_count,
            "distinct_years": year_count,
        },
        "gate_checks": gates,
        "absolute_score": {
            "before": ABSOLUTE_SCORE,
            "after": ABSOLUTE_SCORE,
            "delta": 0,
            "boundary": "Data acquisition and schema validation cannot increase the absolute Finance score.",
        },
        "next_action": (
            "Only after PASS_DATA_AUDIT: freeze one horizon, one released fold, "
            "two strong tree baselines, a calibrated ensemble challenger, and "
            "all utility/calibration gates before viewing test outcomes."
        ),
        "boundary": (
            "This audit establishes public accessibility, versioned file hashes, "
            "schema, scale, grouping keys, and label prevalence. It does not validate "
            "any predictive model or claim SOTA."
        ),
    }


def blocked_access_payload(error: Exception) -> dict[str, Any]:
    gates = {
        "dataset_handle_frozen": True,
        "upstream_commit_frozen": True,
        "all_expected_files_present": False,
        "exactly_seven_expected_parquet_files": False,
        "primary_task_present": False,
        "primary_rows_at_least_500k": False,
        "primary_columns_at_least_130": False,
        "feature_count_at_least_125": False,
        "label_present": False,
        "label_has_at_least_1000_positives": False,
        "label_has_no_nulls": False,
        "group_column_present": False,
        "country_column_present": False,
        "year_column_present": False,
        "company_count_at_least_100k": False,
        "country_count_at_least_4": False,
        "year_count_at_least_10": False,
        "all_hashes_sha256": True,
        "no_data_embedded_in_report": True,
    }
    return {
        "schema": SCHEMA,
        "status": "BLOCKED_DATA_ACCESS",
        "dataset": {
            "handle": DATASET_HANDLE,
            "resolved_path_name": None,
            "version": None,
            "license": "CC BY 4.0 (declared by upstream benchmark)",
            "inventory": [],
            "inventory_sha256": digest([]),
        },
        "upstream": {
            "repository": PINNED_UPSTREAM_REPOSITORY,
            "commit": PINNED_UPSTREAM_COMMIT,
        },
        "primary_task": {
            "file": PRIMARY_TASK,
            "label_column": LABEL_COLUMN,
            "group_column": GROUP_COLUMN,
            "country_column": COUNTRY_COLUMN,
            "year_column": YEAR_COLUMN,
            "feature_count_excluding_four_control_columns": 0,
            "label_summary": {"available": False},
            "distinct_companies": None,
            "distinct_countries": None,
            "distinct_years": None,
        },
        "access_error": {
            "type": type(error).__name__,
            "message": str(error)[:1000],
        },
        "gate_checks": gates,
        "absolute_score": {
            "before": ABSOLUTE_SCORE,
            "after": ABSOLUTE_SCORE,
            "delta": 0,
            "boundary": "Data access failure cannot increase the absolute Finance score.",
        },
        "next_action": (
            "Use a public mirror or user-authorized Kaggle credentials only if the exact "
            "dataset version and hashes can be preserved; otherwise choose another open credit benchmark."
        ),
        "boundary": (
            "The dataset could not be acquired anonymously in the execution environment. "
            "No predictive or SOTA claim is made."
        ),
    }


def runtime_versions() -> dict[str, str | None]:
    def version(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    return {
        "python": platform.python_version(),
        "kagglehub": version("kagglehub"),
        "pyarrow": version("pyarrow"),
    }


def run_audit(output_dir: Path) -> dict[str, Any]:
    try:
        import kagglehub
    except ImportError as exc:
        raise RuntimeError("kagglehub is required") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        resolved_path = Path(kagglehub.dataset_download(DATASET_HANDLE))
    except Exception as exc:
        payload = blocked_access_payload(exc)
        payload["runtime"] = runtime_versions()
        report = {"payload": payload, "sha256": digest(payload)}
        (output_dir / "audit.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output_dir / "audit.md").write_text(
            "\n".join(
                [
                    "# FIN-ABS-004 — V4FinBench public-data audit",
                    "",
                    "- Status: **BLOCKED_DATA_ACCESS**",
                    f"- Error: `{payload['access_error']['type']}: {payload['access_error']['message']}`",
                    "",
                    "**Absolute score remains 423/1000.**",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        print(json.dumps({
            "status": payload["status"],
            "error_type": payload["access_error"]["type"],
            "report_sha256": report["sha256"],
        }, sort_keys=True))
        return report

    inventory = parquet_inventory(resolved_path)
    primary_path = resolved_path / PRIMARY_TASK
    label = label_summary(primary_path) if primary_path.exists() else {"available": False}
    group_count = distinct_count(primary_path, GROUP_COLUMN) if primary_path.exists() else None
    country_count = distinct_count(primary_path, COUNTRY_COLUMN) if primary_path.exists() else None
    year_count = distinct_count(primary_path, YEAR_COLUMN) if primary_path.exists() else None

    payload = build_payload(
        resolved_path=resolved_path,
        inventory=inventory,
        label=label,
        group_count=group_count,
        country_count=country_count,
        year_count=year_count,
    )
    payload["runtime"] = runtime_versions()
    report = {"payload": payload, "sha256": digest(payload)}
    (output_dir / "audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "audit.md").write_text(
        "\n".join(
            [
                "# FIN-ABS-004 — V4FinBench public-data audit",
                "",
                f"- Status: **{payload['status']}**",
                f"- Dataset version: **{payload['dataset']['version']}**",
                f"- Files: **{len(payload['dataset']['inventory'])}**",
                f"- Primary rows: **{payload['primary_task']['label_summary'].get('rows')}**",
                f"- Positive labels: **{payload['primary_task']['label_summary'].get('positive')}**",
                f"- Companies: **{payload['primary_task']['distinct_companies']}**",
                f"- Countries: **{payload['primary_task']['distinct_countries']}**",
                f"- Years: **{payload['primary_task']['distinct_years']}**",
                f"- Report SHA-256: `{report['sha256']}`",
                "",
                "**Absolute score remains 423/1000.**",
                "",
                payload["boundary"],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "version": payload["dataset"]["version"],
                "files": len(payload["dataset"]["inventory"]),
                "rows": payload["primary_task"]["label_summary"].get("rows"),
                "positives": payload["primary_task"]["label_summary"].get("positive"),
                "companies": payload["primary_task"]["distinct_companies"],
                "report_sha256": report["sha256"],
            },
            sort_keys=True,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_audit(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
