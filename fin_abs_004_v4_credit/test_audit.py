from __future__ import annotations

import unittest
from pathlib import Path

from .audit import (
    EXPECTED_FILES,
    blocked_access_payload,
    build_payload,
    dataset_version,
    digest,
)


class V4DataAuditTests(unittest.TestCase):
    def inventory(self) -> list[dict[str, object]]:
        columns = ["company", "country", "year", "main_label"] + [
            f"X{i}" for i in range(1, 132)
        ]
        return [
            {
                "name": name,
                "bytes": 1000,
                "sha256": "a" * 64,
                "rows": 700_000,
                "row_groups": 10,
                "columns": len(columns),
                "column_names": columns,
            }
            for name in EXPECTED_FILES
        ]

    def test_dataset_version_from_kagglehub_path(self) -> None:
        path = Path("/tmp/kagglehub/datasets/owner/name/versions/7")
        self.assertEqual(dataset_version(path), "7")

    def test_complete_audit_passes(self) -> None:
        payload = build_payload(
            resolved_path=Path("/tmp/versions/1"),
            inventory=self.inventory(),
            label={
                "available": True,
                "rows": 700_000,
                "positive": 2_000,
                "negative": 698_000,
                "positive_rate": 2_000 / 700_000,
                "nulls": 0,
            },
            group_count=150_000,
            country_count=4,
            year_count=16,
        )
        self.assertEqual(payload["status"], "PASS_DATA_AUDIT")
        self.assertTrue(all(payload["gate_checks"].values()))
        self.assertEqual(payload["absolute_score"]["after"], 423)

    def test_missing_file_blocks(self) -> None:
        payload = build_payload(
            resolved_path=Path("/tmp/versions/1"),
            inventory=self.inventory()[:-1],
            label={"positive": 2_000, "nulls": 0},
            group_count=150_000,
            country_count=4,
            year_count=16,
        )
        self.assertEqual(payload["status"], "BLOCKED_DATA_AUDIT")
        self.assertFalse(payload["gate_checks"]["all_expected_files_present"])

    def test_low_positive_count_blocks(self) -> None:
        payload = build_payload(
            resolved_path=Path("/tmp/versions/1"),
            inventory=self.inventory(),
            label={"positive": 999, "nulls": 0},
            group_count=150_000,
            country_count=4,
            year_count=16,
        )
        self.assertFalse(payload["gate_checks"]["label_has_at_least_1000_positives"])

    def test_blocked_access_is_typed_and_score_safe(self) -> None:
        payload = blocked_access_payload(RuntimeError("anonymous download blocked"))
        self.assertEqual(payload["status"], "BLOCKED_DATA_ACCESS")
        self.assertEqual(payload["dataset"]["inventory"], [])
        self.assertEqual(payload["absolute_score"]["after"], 423)
        self.assertFalse(payload["gate_checks"]["primary_task_present"])

    def test_digest_is_deterministic(self) -> None:
        self.assertEqual(digest({"b": 2, "a": 1}), digest({"a": 1, "b": 2}))


if __name__ == "__main__":
    unittest.main()
