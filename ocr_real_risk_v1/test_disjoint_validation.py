from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .core import Candidate
from .disjoint_validation import (
    load_seen_processes,
    select_disjoint_shard,
    validation_shard,
)
from .final_partition import process_key
from .isolated_crop import isolated_native_word_box


def candidate(index: int) -> Candidate:
    process = f"PROCESS-{index:04d}"
    return Candidate(
        url=f"https://example.test/{index:04d}.pdf",
        document_type="biddingDocuments",
        process=process,
        ocid=f"ocds-test-{process}",
        institution_code=f"I{index % 3}",
        institution_name=f"Institution {index % 3}",
        source_year=2025,
        source_line=index + 1,
    )


class DisjointValidationTests(unittest.TestCase):
    def test_seen_manifest_is_exactly_bound_to_records(self) -> None:
        rows = [candidate(1), candidate(2)]
        keys = [process_key(row) for row in rows]
        payload = {
            "schema": "ocr-real-risk-development-seen-processes/1",
            "process_keys": keys,
            "records": [
                {
                    "process_key": key,
                    "process": row.process,
                    "ocid": row.ocid,
                }
                for key, row in zip(keys, rows, strict=True)
            ],
            "source_run_id": 1,
            "source_artifact_id": 2,
            "source_report_sha256": "a" * 64,
            "selection_rule": "exclude all attempted processes",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seen.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            seen, census = load_seen_processes(path)
        self.assertEqual(seen, frozenset(keys))
        self.assertEqual(census["seen_processes"], 2)
        self.assertEqual(census["source_artifact_id"], 2)

    def test_seen_processes_never_enter_any_validation_shard(self) -> None:
        rows = [candidate(index) for index in range(40)]
        seen = frozenset(process_key(row) for row in rows[:7])
        selected_sets = []
        for shard_index in range(5):
            selected, census = select_disjoint_shard(
                rows,
                seen,
                shard_index=shard_index,
                shard_count=5,
            )
            keys = {process_key(row) for row in selected}
            self.assertFalse(keys & seen)
            self.assertEqual(census["excluded_seen_processes"], 7)
            selected_sets.append(keys)
        union = set().union(*selected_sets)
        self.assertEqual(union, {process_key(row) for row in rows[7:]})
        for left in range(5):
            for right in range(left + 1, 5):
                self.assertFalse(selected_sets[left] & selected_sets[right])

    def test_shard_is_stable_under_input_reordering(self) -> None:
        rows = [candidate(index) for index in range(20)]
        first, _ = select_disjoint_shard(
            rows,
            frozenset(),
            shard_index=2,
            shard_count=7,
        )
        second, _ = select_disjoint_shard(
            list(reversed(rows)),
            frozenset(),
            shard_index=2,
            shard_count=7,
        )
        self.assertEqual(
            [process_key(row) for row in first],
            [process_key(row) for row in second],
        )
        self.assertTrue(
            all(
                validation_shard(process_key(row), 7) == 2
                for row in first
            )
        )

    def test_isolated_geometry_uses_fixed_padding(self) -> None:
        box = isolated_native_word_box(
            [100.0, 20.0, 200.0, 30.0],
            (600.0, 800.0),
            (1800, 2400),
        )
        self.assertEqual(box, (297, 54, 603, 96))


if __name__ == "__main__":
    unittest.main()
