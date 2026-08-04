from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fin_abs_004_fdic.panel import FEATURE_COLUMNS
from fin_abs_004_fdic.serialization import canonical_json

from .benchmark import benchmark, sha_file
from .model import BASELINES, entity_calibration_bucket


def write_report(path: Path, payload: dict[str, object]) -> dict[str, object]:
    canonical = canonical_json(payload)
    report = {
        "payload": payload,
        "payload_canonical": canonical,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def feature_row(cert: int, split: str, label: int, date: str) -> dict[str, object]:
    rng = np.random.default_rng(20260804 + cert)
    row: dict[str, object] = {
        "CERT": cert,
        "REPDTE": date,
        "split": split,
        "label": label,
        "days_to_failure": 365.0 if label else np.nan,
    }
    for index, column in enumerate(FEATURE_COLUMNS):
        row[column] = float(rng.normal(0.6 * label + 0.01 * index, 0.8))
    return row


def validation_positive_certs() -> tuple[list[int], list[int]]:
    calibration: list[int] = []
    selection: list[int] = []
    cert = 100000
    while len(calibration) < 8 or len(selection) < 8:
        if entity_calibration_bucket(cert) < 50 and len(calibration) < 8:
            calibration.append(cert)
        elif entity_calibration_bucket(cert) >= 50 and len(selection) < 8:
            selection.append(cert)
        cert += 1
    return calibration, selection


class SealedFdicRandomForestBenchmarkTests(unittest.TestCase):
    def test_benchmark_preserves_score_and_emits_bound_artifacts(self) -> None:
        rows: list[dict[str, object]] = []
        for index in range(120):
            rows.append(
                feature_row(
                    1000 + index,
                    "train",
                    int(index < 30),
                    "2004-12-31",
                )
            )

        calibration_positive, selection_positive = validation_positive_certs()
        positive_validation = calibration_positive + selection_positive
        for cert in positive_validation:
            rows.append(feature_row(cert, "validation", 1, "2009-12-31"))
        negative_cert = 200000
        while len([row for row in rows if row["split"] == "validation"]) < 48:
            rows.append(feature_row(negative_cert, "validation", 0, "2009-12-31"))
            negative_cert += 1

        for index in range(120):
            rows.append(
                feature_row(
                    300000 + index,
                    "test",
                    int(index < 50),
                    "2012-12-31" if index % 2 == 0 else "2013-12-31",
                )
            )
        frame = pd.DataFrame(rows)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel_path = root / "panel.csv"
            frame.to_csv(panel_path, index=False, lineterminator="\n")
            split_counts = {
                split: {
                    "rows": int(len(group)),
                    "entities": int(group["CERT"].nunique()),
                    "positives": int(group["label"].sum()),
                    "positive_entities": int(
                        group.loc[group["label"] == 1, "CERT"].nunique()
                    ),
                }
                for split, group in frame.groupby("split", sort=True)
            }
            entity_report_path = root / "entity.json"
            entity_payload: dict[str, object] = {
                "status": "PASS_ENTITY_SPLIT",
                "evaluation_panel": {
                    "feature_file_sha256": sha_file(panel_path),
                    "split_counts": split_counts,
                },
            }
            entity_report = write_report(entity_report_path, entity_payload)
            preflight_path = root / "preflight.json"
            preflight_payload: dict[str, object] = {
                "status": "PASS_PREFLIGHT",
                "panel_file_sha256": sha_file(panel_path),
                "panel_report_sha256": entity_report["sha256"],
                "entity_overlap_counts": {
                    "train_validation": 0,
                    "train_test": 0,
                    "validation_test": 0,
                },
                "split_counts": split_counts,
            }
            write_report(preflight_path, preflight_payload)

            output = root / "result"
            report = benchmark(
                panel_path,
                entity_report_path,
                preflight_path,
                output,
                rf_trees=8,
            )
            payload = report["payload"]
            self.assertEqual(payload["absolute_score"]["before"], 423)
            self.assertEqual(payload["absolute_score"]["after"], 423)
            self.assertEqual(payload["absolute_score"]["delta"], 0)
            self.assertEqual(
                payload["independent_model_reimplementation"], "PENDING"
            )
            self.assertIn("RF_BALANCED", payload["protocol"]["baselines"])
            self.assertIn("RF_COST_SENSITIVE", payload["protocol"]["baselines"])
            self.assertEqual(set(payload["protocol"]["baselines"]), set(BASELINES))
            for filename in (
                "report.json",
                "predictions.jsonl",
                "preprocessing_and_calibration.json",
                "validation_entity_assignments.csv",
            ):
                self.assertTrue((output / filename).is_file(), filename)


if __name__ == "__main__":
    unittest.main()
