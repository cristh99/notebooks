from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fin_abs_004_fdic.serialization import canonical_json

from .preflight import audit_temporal_panel


class TemporalFdicPreflightTests(unittest.TestCase):
    def _write_case(
        self, rows: list[dict[str, object]]
    ) -> tuple[Path, Path, tempfile.TemporaryDirectory[str]]:
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        panel_path = root / "panel.csv"
        pd.DataFrame(rows).to_csv(panel_path, index=False)
        digest = hashlib.sha256(panel_path.read_bytes()).hexdigest()
        payload = {
            "schema": "fin-abs-004/fdic-panel/1",
            "acquisition": {"all_requests_successful": True},
            "evaluation_panel": {"feature_file_sha256": digest},
        }
        canonical = canonical_json(payload)
        report = {
            "payload": payload,
            "payload_canonical": canonical,
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }
        report_path = root / "panel_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return panel_path, report_path, directory

    @staticmethod
    def _row(
        cert: int,
        date: str,
        split: str,
        label: int,
        days: float | None,
    ) -> dict[str, object]:
        return {
            "CERT": cert,
            "REPDTE": date,
            "split": split,
            "label": label,
            "days_to_failure": days,
            "assistance_within_horizon": 0,
        }

    def _passing_rows(self) -> list[dict[str, object]]:
        rows = [self._row(1, "2002-12-31", "train", 1, 365)]
        for index in range(20):
            # CERT 1 deliberately recurs: temporal deployment permits it.
            cert = 1 if index == 0 else 100 + index
            rows.append(
                self._row(cert, "2006-12-31", "validation", 1, 365)
            )
        for index in range(100):
            cert = 1 if index == 0 else 1000 + index
            rows.append(self._row(cert, "2011-12-31", "test", 1, 365))
        return rows

    def test_repeated_entities_are_measured_but_do_not_block(self) -> None:
        panel, report, directory = self._write_case(self._passing_rows())
        try:
            result = audit_temporal_panel(panel, report)
        finally:
            directory.cleanup()
        payload = result["payload"]
        self.assertEqual(payload["status"], "PASS_TEMPORAL_PREFLIGHT")
        self.assertTrue(all(payload["gate_checks"].values()))
        self.assertEqual(
            payload["entity_recurrence_counts"]["train_validation"], 1
        )
        self.assertEqual(payload["entity_recurrence_counts"]["train_test"], 1)
        self.assertFalse(
            payload["deployment_contract"]["unseen_entity_superiority_claimed"]
        )

    def test_negative_label_with_near_failure_blocks(self) -> None:
        rows = self._passing_rows()
        rows.append(self._row(9999, "2011-09-30", "test", 0, 100))
        panel, report, directory = self._write_case(rows)
        try:
            result = audit_temporal_panel(panel, report)
        finally:
            directory.cleanup()
        payload = result["payload"]
        self.assertEqual(payload["status"], "BLOCKED_BEFORE_SEALED_TEST")
        self.assertEqual(payload["contradictory_negative_labels"], 1)
        self.assertFalse(
            payload["gate_checks"][
                "negative_labels_do_not_hide_failure_within_horizon"
            ]
        )

    def test_incomplete_outcome_gap_blocks(self) -> None:
        rows = self._passing_rows()
        rows[0]["REPDTE"] = "2004-12-31"
        panel, report, directory = self._write_case(rows)
        try:
            result = audit_temporal_panel(panel, report)
        finally:
            directory.cleanup()
        self.assertEqual(
            result["payload"]["status"], "BLOCKED_BEFORE_SEALED_TEST"
        )
        self.assertFalse(
            result["payload"]["gate_checks"]["complete_two_year_outcome_gaps"]
        )


if __name__ == "__main__":
    unittest.main()
