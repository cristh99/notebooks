from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .serialization import canonical_json, digest_json

SCHEMA = "fin-abs-004/fdic-entity-disjoint-panel/1"
ENTITY_SPLIT_SEED = "FIN-ABS-004-ENTITY-SPLIT-V1"
TRAIN_BUCKET_END = 35
VALIDATION_BUCKET_END = 75


def sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def entity_bucket(cert: int) -> int:
    value = hashlib.sha256(
        f"{ENTITY_SPLIT_SEED}|{int(cert)}".encode("utf-8")
    ).hexdigest()
    return int(value[:16], 16) % 100


def assigned_split(source_split: str, bucket: int) -> str | None:
    if source_split == "train" and bucket < TRAIN_BUCKET_END:
        return "train"
    if (
        source_split == "validation"
        and TRAIN_BUCKET_END <= bucket < VALIDATION_BUCKET_END
    ):
        return "validation"
    if source_split == "test" and bucket >= VALIDATION_BUCKET_END:
        return "test"
    return None


def build_entity_panel(
    source_panel_path: Path,
    source_report_path: Path,
    output_panel_path: Path,
    output_report_path: Path,
) -> dict[str, Any]:
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    source_contract = source_report.get("payload", {}).get("evaluation_panel", {})
    source_sha = sha_file(source_panel_path)
    if source_sha != source_contract.get("feature_file_sha256"):
        raise ValueError("source panel hash does not match its report")

    frame = pd.read_csv(source_panel_path, low_memory=False)
    required = {"CERT", "REPDTE", "split", "label"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"source panel missing required fields: {missing}")
    frame["CERT"] = pd.to_numeric(frame["CERT"], errors="raise").astype(int)
    frame["REPDTE"] = pd.to_datetime(frame["REPDTE"], errors="raise")
    frame["label"] = pd.to_numeric(frame["label"], errors="raise").astype(int)
    frame["source_split"] = frame["split"].astype(str)
    frame["entity_bucket"] = frame["CERT"].map(entity_bucket)
    frame["split"] = [
        assigned_split(source, int(bucket))
        for source, bucket in zip(
            frame["source_split"], frame["entity_bucket"], strict=True
        )
    ]
    retained = frame.loc[frame["split"].notna()].copy()
    retained["split"] = retained["split"].astype(str)
    retained = retained.sort_values(["split", "REPDTE", "CERT"]).reset_index(
        drop=True
    )

    output_panel_path.parent.mkdir(parents=True, exist_ok=True)
    retained.to_csv(
        output_panel_path,
        index=False,
        float_format="%.17g",
        date_format="%Y-%m-%d",
        lineterminator="\n",
    )

    split_counts: dict[str, dict[str, int]] = {}
    entity_sets: dict[str, set[int]] = {}
    for split in ("train", "validation", "test"):
        subset = retained.loc[retained["split"] == split]
        entity_sets[split] = set(subset["CERT"].tolist())
        split_counts[split] = {
            "rows": int(len(subset)),
            "entities": int(subset["CERT"].nunique()),
            "positives": int(subset["label"].sum()),
            "positive_entities": int(
                subset.loc[subset["label"] == 1, "CERT"].nunique()
            ),
        }
    overlaps = {
        "train_validation": len(
            entity_sets["train"] & entity_sets["validation"]
        ),
        "train_test": len(entity_sets["train"] & entity_sets["test"]),
        "validation_test": len(
            entity_sets["validation"] & entity_sets["test"]
        ),
    }
    checks = {
        "source_panel_hash_exact": source_sha
        == source_contract.get("feature_file_sha256"),
        "zero_bank_quarter_duplicates": int(
            retained.duplicated(["CERT", "REPDTE"]).sum()
        )
        == 0,
        "zero_entity_overlap": all(value == 0 for value in overlaps.values()),
        "all_three_splits_present": all(
            split_counts[split]["rows"] > 0
            for split in ("train", "validation", "test")
        ),
        "train_positive_entities_at_least_30": split_counts["train"][
            "positive_entities"
        ]
        >= 30,
        "validation_positive_entities_at_least_10": split_counts[
            "validation"
        ]["positive_entities"]
        >= 10,
        "test_positive_entities_at_least_50": split_counts["test"][
            "positive_entities"
        ]
        >= 50,
        "validation_positive_rows_at_least_20": split_counts["validation"][
            "positives"
        ]
        >= 20,
        "test_positive_rows_at_least_100": split_counts["test"]["positives"]
        >= 100,
    }
    passed = all(checks.values())
    payload = {
        "schema": SCHEMA,
        "source": {
            "panel_file_sha256": source_sha,
            "panel_report_sha256": source_report.get("sha256"),
        },
        "protocol": {
            "seed": ENTITY_SPLIT_SEED,
            "bucket_rule": {
                "train": [0, TRAIN_BUCKET_END - 1],
                "validation": [TRAIN_BUCKET_END, VALIDATION_BUCKET_END - 1],
                "test": [VALIDATION_BUCKET_END, 99],
            },
            "date_rule": (
                "retain a bank only in the original temporal window that "
                "matches its immutable hash bucket"
            ),
            "selection_information": (
                "CERT and original temporal split only; no feature value, "
                "model score, prediction, or sealed-test performance"
            ),
        },
        "evaluation_panel": {
            "rows": int(len(retained)),
            "dropped_rows": int(len(frame) - len(retained)),
            "split_counts": split_counts,
            "entity_overlap_counts": overlaps,
            "feature_file": output_panel_path.name,
            "feature_file_sha256": sha_file(output_panel_path),
            "panel_rows_sha256": digest_json(
                retained.to_dict(orient="records")
            ),
            "zero_bank_quarter_duplicates": int(
                retained.duplicated(["CERT", "REPDTE"]).sum()
            )
            == 0,
        },
        "gate_checks": checks,
        "status": "PASS_ENTITY_SPLIT" if passed else "BLOCKED_ENTITY_SPLIT",
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": "Split construction only; no model evaluated.",
        },
    }
    canonical = canonical_json(payload)
    report = {
        "payload": payload,
        "payload_canonical": canonical,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
    output_report_path.parent.mkdir(parents=True, exist_ok=True)
    output_report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-panel", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output-panel", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args()
    result = build_entity_panel(
        args.source_panel,
        args.source_report,
        args.output_panel,
        args.output_report,
    )
    payload = result["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "split_counts": payload["evaluation_panel"]["split_counts"],
                "overlaps": payload["evaluation_panel"][
                    "entity_overlap_counts"
                ],
                "sha256": result["sha256"],
            },
            sort_keys=True,
        )
    )
    if payload["status"] != "PASS_ENTITY_SPLIT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
