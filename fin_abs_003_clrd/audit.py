from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA = "fin-abs-003/clrd-data-audit/1"
SOURCE_COMMIT = "2f6ea125d17e29d018b56e4df85eda52ac8ac206"
SOURCE_BLOB = "04e54cfa41e7bd879877e5c5aea5e63a6d20d29b"
SPLIT_SEED = "FIN-ABS-003-SPLIT-V1"
CUTOFFS = (1994, 1995, 1996)
TARGET_YEAR = 1997
REQUIRED_COLUMNS = {
    "GRCODE",
    "GRNAME",
    "AccidentYear",
    "DevelopmentYear",
    "DevelopmentLag",
    "IncurLoss",
    "CumPaidLoss",
    "BulkLoss",
    "EarnedPremDIR",
    "EarnedPremCeded",
    "EarnedPremNet",
    "Single",
    "PostedReserve97",
    "LOB",
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


def split_for_grcode(value: Any) -> str:
    key = f"{str(value).strip()}|{SPLIT_SEED}".encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % 100
    if bucket < 60:
        return "train"
    if bucket < 80:
        return "validation"
    return "test"


def normalized_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"CLRD missing required columns: {missing}")
    output = frame.copy()
    for column in (
        "AccidentYear",
        "DevelopmentYear",
        "DevelopmentLag",
        "IncurLoss",
        "CumPaidLoss",
        "BulkLoss",
        "EarnedPremDIR",
        "EarnedPremCeded",
        "EarnedPremNet",
        "Single",
        "PostedReserve97",
    ):
        output[column] = pd.to_numeric(output[column], errors="coerce")
    output["GRCODE"] = output["GRCODE"].astype(str).str.strip()
    output["GRNAME"] = output["GRNAME"].astype(str).str.strip()
    output["LOB"] = output["LOB"].astype(str).str.strip()
    output["split"] = output["GRCODE"].map(split_for_grcode)
    return output


def build_cases(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    indexed = frame.set_index(
        ["GRCODE", "LOB", "AccidentYear", "DevelopmentYear"],
        drop=False,
    ).sort_index()
    rows: list[dict[str, Any]] = []
    excluded = Counter()
    group_columns = ["GRCODE", "LOB", "AccidentYear"]
    for (grcode, lob, accident_year), group in frame.groupby(
        group_columns, sort=True, dropna=False
    ):
        targets = group.loc[group["DevelopmentYear"] == TARGET_YEAR]
        if len(targets) != 1:
            excluded["missing_or_duplicate_target"] += len(CUTOFFS)
            continue
        target = targets.iloc[0]
        target_paid = float(target["CumPaidLoss"])
        premium = float(target["EarnedPremNet"])
        for cutoff in CUTOFFS:
            visible = group.loc[group["DevelopmentYear"] == cutoff]
            if len(visible) != 1:
                excluded["missing_or_duplicate_current"] += 1
                continue
            current = visible.iloc[0]
            current_paid = float(current["CumPaidLoss"])
            if not np.isfinite(current_paid) or current_paid <= 0:
                excluded["nonpositive_current"] += 1
                continue
            if not np.isfinite(target_paid):
                excluded["missing_target_paid"] += 1
                continue
            if target_paid < current_paid:
                excluded["target_below_current"] += 1
                continue
            if not np.isfinite(premium) or premium <= 0:
                excluded["nonpositive_premium"] += 1
                continue
            rows.append(
                {
                    "GRCODE": str(grcode),
                    "GRNAME": str(current["GRNAME"]),
                    "LOB": str(lob),
                    "AccidentYear": int(accident_year),
                    "cutoff": cutoff,
                    "current_development_lag": int(current["DevelopmentLag"]),
                    "target_development_lag": int(target["DevelopmentLag"]),
                    "current_paid": current_paid,
                    "target_paid": target_paid,
                    "actual_reserve": target_paid - current_paid,
                    "earned_premium_net": premium,
                    "split": split_for_grcode(grcode),
                }
            )
    cases = pd.DataFrame(rows)
    if not cases.empty:
        cases = cases.sort_values(
            ["split", "LOB", "GRCODE", "cutoff", "AccidentYear"]
        ).reset_index(drop=True)
        cases["case_id"] = cases.apply(
            lambda row: hashlib.sha256(
                (
                    f"{row.GRCODE}|{row.LOB}|{int(row.AccidentYear)}|"
                    f"{int(row.cutoff)}|FIN-ABS-003-CASE-V1"
                ).encode("utf-8")
            ).hexdigest(),
            axis=1,
        )
    return cases, dict(sorted(excluded.items()))


def audit(path: Path) -> dict[str, Any]:
    transport_sha = file_sha256(path)
    frame = normalized_frame(path)
    triangles = frame[["GRCODE", "LOB"]].drop_duplicates()
    entities = frame[["GRCODE", "split"]].drop_duplicates()
    split_leakage = int(
        entities.groupby("GRCODE")["split"].nunique().gt(1).sum()
    )
    duplicate_cells = int(
        frame.duplicated(
            ["GRCODE", "LOB", "AccidentYear", "DevelopmentYear"]
        ).sum()
    )
    cases, excluded = build_cases(frame)
    case_split_counts = (
        cases["split"].value_counts().sort_index().astype(int).to_dict()
        if not cases.empty
        else {}
    )
    entity_split_counts = (
        entities["split"].value_counts().sort_index().astype(int).to_dict()
    )
    lob_counts = (
        triangles["LOB"].value_counts().sort_index().astype(int).to_dict()
    )
    case_lob_counts = (
        cases["LOB"].value_counts().sort_index().astype(int).to_dict()
        if not cases.empty
        else {}
    )
    cutoff_counts = (
        {
            str(int(key)): int(value)
            for key, value in cases["cutoff"].value_counts().sort_index().items()
        }
        if not cases.empty
        else {}
    )
    checks = {
        "required_columns_present": REQUIRED_COLUMNS.issubset(frame.columns),
        "row_count_at_least_40000": len(frame) >= 40000,
        "triangles_at_least_500": len(triangles) >= 500,
        "six_lines_present": len(lob_counts) == 6,
        "development_lags_one_to_ten": set(
            int(value)
            for value in frame["DevelopmentLag"].dropna().unique()
        )
        == set(range(1, 11)),
        "accident_years_1988_to_1997": set(
            int(value) for value in frame["AccidentYear"].dropna().unique()
        )
        == set(range(1988, 1998)),
        "development_years_end_1997": int(frame["DevelopmentYear"].max())
        == 1997,
        "zero_duplicate_cells": duplicate_cells == 0,
        "zero_entity_split_leakage": split_leakage == 0,
        "all_splits_nonempty": set(case_split_counts) == {
            "train",
            "validation",
            "test",
        },
        "eligible_cases_at_least_5000": len(cases) >= 5000,
        "all_six_lines_in_cases": len(case_lob_counts) == 6,
    }
    payload = {
        "schema": SCHEMA,
        "source": {
            "repository": "casact/chainladder-python",
            "source_commit": SOURCE_COMMIT,
            "source_blob": SOURCE_BLOB,
            "path": "chainladder/utils/data/clrd.csv",
            "transport_sha256": transport_sha,
        },
        "dataset": {
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "entities": int(frame["GRCODE"].nunique()),
            "triangles": int(len(triangles)),
            "lines": lob_counts,
            "accident_year_min": int(frame["AccidentYear"].min()),
            "accident_year_max": int(frame["AccidentYear"].max()),
            "development_year_min": int(frame["DevelopmentYear"].min()),
            "development_year_max": int(frame["DevelopmentYear"].max()),
            "duplicate_cells": duplicate_cells,
        },
        "split": {
            "seed": SPLIT_SEED,
            "entity_counts": entity_split_counts,
            "case_counts": case_split_counts,
            "entity_leakage": split_leakage,
        },
        "cases": {
            "eligible": int(len(cases)),
            "line_counts": case_lob_counts,
            "cutoff_counts": cutoff_counts,
            "excluded": excluded,
            "cases_sha256": digest(cases.to_dict(orient="records")),
        },
        "gate_checks": checks,
        "status": "PASS_DATA_AUDIT" if all(checks.values()) else "OPEN_DATA_AUDIT",
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": "Data acquisition and audit do not establish reserving superiority.",
        },
    }
    payload_canonical = canonical(payload)
    return {
        "payload": payload,
        "payload_canonical": payload_canonical,
        "sha256": hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest(),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {key: value for key, value in result.items() if key != "cases"}
    (args.output_dir / "data_audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result["cases"].to_csv(args.output_dir / "eligible_cases.csv", index=False)
    print(
        json.dumps(
            {
                "status": report["payload"]["status"],
                "transport_sha256": report["payload"]["source"][
                    "transport_sha256"
                ],
                "rows": report["payload"]["dataset"]["rows"],
                "triangles": report["payload"]["dataset"]["triangles"],
                "eligible_cases": report["payload"]["cases"]["eligible"],
                "split": report["payload"]["split"]["case_counts"],
                "report_sha256": report["sha256"],
            },
            sort_keys=True,
        )
    )
    if report["payload"]["status"] != "PASS_DATA_AUDIT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
