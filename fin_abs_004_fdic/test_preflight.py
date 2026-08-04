from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from .preflight import audit_panel


class FdicPreflightTests(unittest.TestCase):
    def _write_case(self, rows: list[dict[str, object]]) -> tuple[Path, Path, tempfile.TemporaryDirectory[str]]:
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        panel_path = root / "panel.csv"
        frame = pd.DataFrame(rows)
        frame.to_csv(panel_path, index=False)
        import hashlib

        digest = hashlib.sha256(panel_path.read_bytes()).hexdigest()
        report_path = root / "panel_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "payload": {
                        "evaluation_panel": {"feature_file_sha256": digest}
                    },
                    "sha256": "panel-report",
                }
            ),
            encoding="utf-8",
        )
        return panel_path, report_path, directory

    def test_entity_overlap_blocks_before_test(self) -> None:
        rows: list[dict[str, object]] = []
        for index in range(20):
            rows.append(
                {
                    "CERT": index + 1,
                    "REPDTE": "2002-12-31",
                    "split": "train",
                    "label": 1 if index == 0 else 0,
                }
            )
            rows.append(
                {
                    "CERT": index + 1,
                    "REPDTE": "2006-12-31",
                    "split": "validation",
                    "label": 1,
                }
            )
        for index in range(100):
            rows.append(
                {
                    "CERT": 1000 + index,
                    "REPDTE": "2011-12-31",
                    "split": "test",
                    "label": 1,
                }
            )
        panel, report, directory = self._write_case(rows)
        try:
            result = audit_panel(panel, report)
        finally:
            directory.cleanup()
        self.assertEqual(
            result["payload"]["status"], "BLOCKED_BEFORE_SEALED_TEST"
        )
        self.assertEqual(
            result["payload"]["entity_overlap_counts"]["train_validation"],
            20,
        )
        self.assertFalse(
            result["payload"]["gate_checks"]["zero_entity_overlap"]
        )

    def test_disjoint_splits_pass(self) -> None:
        rows: list[dict[str, object]] = []
        for split, date, start, count in (
            ("train", "2002-12-31", 1, 20),
            ("validation", "2006-12-31", 101, 20),
            ("test", "2011-12-31", 1001, 100),
        ):
            for index in range(count):
                rows.append(
                    {
                        "CERT": start + index,
                        "REPDTE": date,
                        "split": split,
                        "label": 1,
                    }
                )
        panel, report, directory = self._write_case(rows)
        try:
            result = audit_panel(panel, report)
        finally:
            directory.cleanup()
        self.assertEqual(result["payload"]["status"], "PASS_PREFLIGHT")
        self.assertTrue(all(result["payload"]["gate_checks"].values()))


if __name__ == "__main__":
    unittest.main()
