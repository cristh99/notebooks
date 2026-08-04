from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .serialization import canonical_json

SCHEMA = "fin-abs-004/fdic-preflight/1"
SPLITS = ("train", "validation", "test")


def sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def audit_panel(panel_path: Path, panel_report_path: Path) -> dict[str, Any]:
    report = json.loads(panel_report_path.read_text(encoding="utf-8"))
    frame = pd.read_csv(panel_path, low_memory=False)
    required = {"CERT", "REPDTE", "split", "label"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"panel missing required fields: {missing}")

    frame["CERT"] = pd.to_numeric(frame["CERT"], errors="raise").astype(int)
    frame["REPDTE"] = pd.to_datetime(frame["REPDTE"], errors="raise")
    frame["label"] = pd.to_numeric(frame["label"], errors="raise").astype(int)
    unknown_splits = sorted(set(frame["split"].dropna()) - set(SPLITS))

    entities = {
        split: set(frame.loc[frame["split"] == split, "CERT"].tolist())
        for split in SPLITS
    }
    overlaps = {
        "train_validation": sorted(entities["train"] & entities["validation"]),
        "train_test": sorted(entities["train"] & entities["test"]),
        "validation_test": sorted(entities["validation"] & entities["test"]),
    }
    overlap_counts = {key: len(value) for key, value in overlaps.items()}
    samples = {key: value[:20] for key, value in overlaps.items()}

    split_dates: dict[str, dict[str, str | None]] = {}
    split_counts: dict[str, dict[str, int]] = {}
    for split in SPLITS:
        subset = frame.loc[frame["split"] == split]
        split_dates[split] = {
            "start": subset["REPDTE"].min().date().isoformat() if not subset.empty else None,
            "end": subset["REPDTE"].max().date().isoformat() if not subset.empty else None,
        }
        split_counts[split] = {
            "rows": int(len(subset)),
            "entities": int(subset["CERT"].nunique()),
            "positive_rows": int(subset["label"].sum()),
            "positive_entities": int(
                subset.loc[subset["label"] == 1, "CERT"].nunique()
            ),
        }

    temporal_order = (
        split_dates["train"]["end"] is not None
        and split_dates["validation"]["start"] is not None
        and split_dates["validation"]["end"] is not None
        and split_dates["test"]["start"] is not None
        and split_dates["train"]["end"] < split_dates["validation"]["start"]
        and split_dates["validation"]["end"] < split_dates["test"]["start"]
    )
    contract = report.get("payload", {}).get("evaluation_panel", {})
    checks = {
        "panel_file_hash_matches_report": sha_file(panel_path)
        == contract.get("feature_file_sha256"),
        "known_splits_only": not unknown_splits,
        "zero_bank_quarter_duplicates": int(
            frame.duplicated(["CERT", "REPDTE"]).sum()
        )
        == 0,
        "strict_temporal_order": bool(temporal_order),
        "zero_entity_overlap": all(value == 0 for value in overlap_counts.values()),
        "train_positive_rows": split_counts["train"]["positive_rows"] > 0,
        "validation_positive_rows_at_least_20": split_counts["validation"][
            "positive_rows"
        ]
        >= 20,
        "test_positive_rows_at_least_100": split_counts["test"][
            "positive_rows"
        ]
        >= 100,
    }
    passed = all(checks.values())
    payload = {
        "schema": SCHEMA,
        "panel_file_sha256": sha_file(panel_path),
        "panel_report_sha256": report.get("sha256"),
        "split_counts": split_counts,
        "split_dates": split_dates,
        "entity_overlap_counts": overlap_counts,
        "entity_overlap_samples": samples,
        "unknown_splits": unknown_splits,
        "gate_checks": checks,
        "status": "PASS_PREFLIGHT" if passed else "BLOCKED_BEFORE_SEALED_TEST",
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
        },
    }
    canonical = canonical_json(payload)
    return {
        "payload": payload,
        "payload_canonical": canonical,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--panel-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_panel(args.panel, args.panel_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": result["payload"]["status"],
                "overlaps": result["payload"]["entity_overlap_counts"],
                "split_counts": result["payload"]["split_counts"],
                "sha256": result["sha256"],
            },
            sort_keys=True,
        )
    )
    if result["payload"]["status"] != "PASS_PREFLIGHT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
