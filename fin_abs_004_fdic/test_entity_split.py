from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from .entity_split import (
    TRAIN_BUCKET_END,
    VALIDATION_BUCKET_END,
    assigned_split,
    build_entity_panel,
    entity_bucket,
)


class EntitySplitTests(unittest.TestCase):
    def _cert_in_range(self, lower: int, upper: int, start: int) -> int:
        for cert in range(start, start + 100000):
            if lower <= entity_bucket(cert) <= upper:
                return cert
        raise AssertionError("no deterministic certificate found in bucket range")

    def test_assignment_uses_source_window_and_hash_only(self) -> None:
        train_cert = self._cert_in_range(0, TRAIN_BUCKET_END - 1, 1)
        validation_cert = self._cert_in_range(
            TRAIN_BUCKET_END, VALIDATION_BUCKET_END - 1, 100001
        )
        test_cert = self._cert_in_range(
            VALIDATION_BUCKET_END, 99, 200001
        )
        self.assertEqual(assigned_split("train", entity_bucket(train_cert)), "train")
        self.assertEqual(
            assigned_split("validation", entity_bucket(validation_cert)),
            "validation",
        )
        self.assertEqual(assigned_split("test", entity_bucket(test_cert)), "test")
        self.assertIsNone(assigned_split("test", entity_bucket(train_cert)))

    def test_build_is_disjoint_deterministic_and_hash_bound(self) -> None:
        rows: list[dict[str, object]] = []
        starts = {"train": 1, "validation": 100001, "test": 200001}
        ranges = {
            "train": (0, TRAIN_BUCKET_END - 1),
            "validation": (TRAIN_BUCKET_END, VALIDATION_BUCKET_END - 1),
            "test": (VALIDATION_BUCKET_END, 99),
        }
        dates = {
            "train": "2002-12-31",
            "validation": "2006-12-31",
            "test": "2011-12-31",
        }
        counts = {"train": 30, "validation": 20, "test": 100}
        for split, count in counts.items():
            lower, upper = ranges[split]
            cursor = starts[split]
            for _ in range(count):
                cert = self._cert_in_range(lower, upper, cursor)
                cursor = cert + 1
                rows.append(
                    {
                        "CERT": cert,
                        "REPDTE": dates[split],
                        "split": split,
                        "label": 1,
                        "ASSET": 100.0,
                    }
                )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_panel = root / "source.csv"
            pd.DataFrame(rows).to_csv(source_panel, index=False)
            source_sha = hashlib.sha256(source_panel.read_bytes()).hexdigest()
            source_report = root / "source_report.json"
            source_report.write_text(
                json.dumps(
                    {
                        "payload": {
                            "evaluation_panel": {
                                "feature_file_sha256": source_sha
                            }
                        },
                        "sha256": "source-report",
                    }
                ),
                encoding="utf-8",
            )
            output_panel = root / "entity.csv"
            output_report = root / "entity_report.json"
            first = build_entity_panel(
                source_panel, source_report, output_panel, output_report
            )
            first_bytes = output_panel.read_bytes()
            second = build_entity_panel(
                source_panel, source_report, output_panel, output_report
            )
            self.assertEqual(first, second)
            self.assertEqual(first_bytes, output_panel.read_bytes())
            self.assertEqual(first["payload"]["status"], "PASS_ENTITY_SPLIT")
            self.assertTrue(all(first["payload"]["gate_checks"].values()))
            self.assertEqual(
                first["payload"]["evaluation_panel"]["entity_overlap_counts"],
                {
                    "train_validation": 0,
                    "train_test": 0,
                    "validation_test": 0,
                },
            )


if __name__ == "__main__":
    unittest.main()
