from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from fin_abs_004_fdic.serialization import canonical_json

SCHEMA = "fin-abs-004b/fdic-temporal-preflight/1"
SPLITS = ("train", "validation", "test")
LABEL_HORIZON_DAYS = 730
OUTCOME_CENSOR_DATE = pd.Timestamp("2013-12-31")


def sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _validate_panel_report(report: dict[str, Any]) -> bool:
    payload = report.get("payload")
    canonical = report.get("payload_canonical")
    digest = report.get("sha256")
    if not isinstance(payload, dict) or not isinstance(canonical, str) or not isinstance(digest, str):
        return False
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != digest:
        return False
    try:
        rebuilt = canonical_json(json.loads(canonical))
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    return rebuilt == canonical_json(payload)


def audit_temporal_panel(panel_path: Path, panel_report_path: Path) -> dict[str, Any]:
    report = json.loads(panel_report_path.read_text(encoding="utf-8"))
    frame = pd.read_csv(panel_path, low_memory=False)
    required = {
        "CERT",
        "REPDTE",
        "split",
        "label",
        "days_to_failure",
        "assistance_within_horizon",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"panel missing required fields: {missing}")

    frame["CERT"] = pd.to_numeric(frame["CERT"], errors="raise").astype(int)
    frame["REPDTE"] = pd.to_datetime(frame["REPDTE"], errors="raise")
    frame["label"] = pd.to_numeric(frame["label"], errors="raise").astype(int)
    frame["days_to_failure"] = pd.to_numeric(
        frame["days_to_failure"], errors="coerce"
    )
    frame["assistance_within_horizon"] = pd.to_numeric(
        frame["assistance_within_horizon"], errors="raise"
    ).astype(int)

    unknown_splits = sorted(set(frame["split"].dropna()) - set(SPLITS))
    invalid_labels = int((~frame["label"].isin([0, 1])).sum())
    invalid_assistance = int(
        (~frame["assistance_within_horizon"].isin([0, 1])).sum()
    )

    entities = {
        split: set(frame.loc[frame["split"] == split, "CERT"].tolist())
        for split in SPLITS
    }
    overlap_counts = {
        "train_validation": len(entities["train"] & entities["validation"]),
        "train_test": len(entities["train"] & entities["test"]),
        "validation_test": len(entities["validation"] & entities["test"]),
    }
    overlap_samples = {
        "train_validation": sorted(entities["train"] & entities["validation"])[
            :20
        ],
        "train_test": sorted(entities["train"] & entities["test"])[
            :20
        ],
        "validation_test": sorted(
            entities["validation"] & entities["test"]
        )[:20],
    }

    split_dates: dict[str, dict[str, str | None]] = {}
    split_counts: dict[str, dict[str, int]] = {}
    entity_novelty: dict[str, dict[str, int]] = {}
    prior_entities: set[int] = set()
    for split in SPLITS:
        subset = frame.loc[frame["split"] == split]
        split_dates[split] = {
            "start": subset["REPDTE"].min().date().isoformat()
            if not subset.empty
            else None,
            "end": subset["REPDTE"].max().date().isoformat()
            if not subset.empty
            else None,
        }
        current_entities = set(subset["CERT"].tolist())
        split_counts[split] = {
            "rows": int(len(subset)),
            "entities": int(len(current_entities)),
            "positive_rows": int(subset["label"].sum()),
            "positive_entities": int(
                subset.loc[subset["label"] == 1, "CERT"].nunique()
            ),
        }
        entity_novelty[split] = {
            "seen_in_prior_splits": int(len(current_entities & prior_entities)),
            "new_to_this_split": int(len(current_entities - prior_entities)),
        }
        prior_entities |= current_entities

    temporal_order = (
        split_dates["train"]["end"] is not None
        and split_dates["validation"]["start"] is not None
        and split_dates["validation"]["end"] is not None
        and split_dates["test"]["start"] is not None
        and split_dates["test"]["end"] is not None
        and split_dates["train"]["end"] < split_dates["validation"]["start"]
        and split_dates["validation"]["end"] < split_dates["test"]["start"]
    )
    outcome_gaps = False
    final_test_observable = False
    if temporal_order:
        train_end = pd.Timestamp(split_dates["train"]["end"])
        validation_start = pd.Timestamp(split_dates["validation"]["start"])
        validation_end = pd.Timestamp(split_dates["validation"]["end"])
        test_start = pd.Timestamp(split_dates["test"]["start"])
        test_end = pd.Timestamp(split_dates["test"]["end"])
        outcome_gaps = bool(
            train_end + pd.Timedelta(days=LABEL_HORIZON_DAYS)
            < validation_start
            and validation_end + pd.Timedelta(days=LABEL_HORIZON_DAYS)
            < test_start
        )
        final_test_observable = bool(
            test_end + pd.Timedelta(days=LABEL_HORIZON_DAYS)
            <= OUTCOME_CENSOR_DATE
        )

    positive = frame["label"] == 1
    positive_days_valid = bool(
        frame.loc[positive, "days_to_failure"]
        .between(1, LABEL_HORIZON_DAYS, inclusive="both")
        .all()
    )
    contradictory_negative = int(
        (
            (~positive)
            & frame["days_to_failure"].between(
                1, LABEL_HORIZON_DAYS, inclusive="both"
            )
        ).sum()
    )

    panel_contract = report.get("payload", {}).get("evaluation_panel", {})
    acquisition_contract = report.get("payload", {}).get("acquisition", {})
    checks = {
        "panel_report_semantically_valid": _validate_panel_report(report),
        "panel_file_hash_matches_report": sha_file(panel_path)
        == panel_contract.get("feature_file_sha256"),
        "known_splits_only": not unknown_splits,
        "binary_labels_only": invalid_labels == 0,
        "binary_assistance_indicator_only": invalid_assistance == 0,
        "zero_bank_quarter_duplicates": int(
            frame.duplicated(["CERT", "REPDTE"]).sum()
        )
        == 0,
        "strict_temporal_order": bool(temporal_order),
        "complete_two_year_outcome_gaps": bool(outcome_gaps),
        "sealed_test_outcomes_fully_observable": bool(final_test_observable),
        "positive_labels_have_future_failure_within_horizon": positive_days_valid,
        "negative_labels_do_not_hide_failure_within_horizon": contradictory_negative
        == 0,
        "all_official_requests_successful": acquisition_contract.get(
            "all_requests_successful"
        )
        is True,
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
        "deployment_contract": {
            "generalization_axis": "future_calendar_regimes",
            "entity_recurrence": (
                "Permitted and measured: supervised banks may reappear in later "
                "quarters. No future row, outcome or parameter may enter an earlier "
                "forecast. Uncertainty is clustered by CERT."
            ),
            "unseen_entity_superiority_claimed": False,
            "label_horizon_days": LABEL_HORIZON_DAYS,
            "outcome_censor_date": OUTCOME_CENSOR_DATE.date().isoformat(),
        },
        "panel_file_sha256": sha_file(panel_path),
        "panel_report_sha256": report.get("sha256"),
        "split_counts": split_counts,
        "split_dates": split_dates,
        "entity_recurrence_counts": overlap_counts,
        "entity_recurrence_samples": overlap_samples,
        "entity_novelty": entity_novelty,
        "unknown_splits": unknown_splits,
        "invalid_labels": invalid_labels,
        "invalid_assistance_indicators": invalid_assistance,
        "contradictory_negative_labels": contradictory_negative,
        "gate_checks": checks,
        "status": "PASS_TEMPORAL_PREFLIGHT"
        if passed
        else "BLOCKED_BEFORE_SEALED_TEST",
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": "Temporal preflight only; no model performance evaluated.",
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
    result = audit_temporal_panel(args.panel, args.panel_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": result["payload"]["status"],
                "split_counts": result["payload"]["split_counts"],
                "entity_recurrence_counts": result["payload"][
                    "entity_recurrence_counts"
                ],
                "sha256": result["sha256"],
            },
            sort_keys=True,
        )
    )
    if result["payload"]["status"] != "PASS_TEMPORAL_PREFLIGHT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
