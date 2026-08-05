from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from .distributed_throughput import (
    PARTITION_REPORT_SCHEMA,
    aggregate_outputs,
    balanced_assignments,
    encode_rows,
)


def write_output(
    root: Path,
    *,
    partition_count: int,
    partition_index: int,
    rows: list[dict],
    seconds: float,
    started: float,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = encode_rows(rows)
    (root / "rows.jsonl").write_bytes(payload)
    report = {
        "schema": PARTITION_REPORT_SCHEMA,
        "page_pack_stable_payload_sha256": "a" * 64,
        "partition_count": partition_count,
        "partition_index": partition_index,
        "page_indices": sorted(row["page_index"] for row in rows),
        "page_count": len(rows),
        "token_count": sum(len(row["tokens"]) for row in rows),
        "rows_sha256": hashlib.sha256(payload).hexdigest(),
        "ocr_started_epoch": started,
        "ocr_ended_epoch": started + seconds,
        "ocr_wall_seconds": seconds,
        "runtime": {"tesseract": "tesseract synthetic"},
    }
    (root / "report.json").write_text(
        json.dumps(report, sort_keys=True) + "\n", encoding="utf-8"
    )


def row(index: int, text: str | None = None) -> dict:
    return {
        "page_index": index,
        "page_sha256": str(index) * 64,
        "tokens": [{"token_index": 0, "text": text or str(index)}],
    }


class DistributedThroughputTests(unittest.TestCase):
    def test_balanced_assignments_cover_once_and_are_stable(self) -> None:
        pages = [
            {"page_index": index, "width": width, "height": height}
            for index, (width, height) in enumerate(
                [(100, 100), (200, 100), (50, 50), (300, 100), (80, 90)]
            )
        ]
        first = balanced_assignments(pages, 3)
        second = balanced_assignments(list(reversed(pages)), 3)
        self.assertEqual(first, second)
        flattened = [value for values in first for value in values]
        self.assertEqual(sorted(flattened), list(range(5)))
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_encode_rows_is_order_independent(self) -> None:
        self.assertEqual(encode_rows([row(1), row(0)]), encode_rows([row(0), row(1)]))

    def test_exact_parallel_output_can_pass_tenfold_service_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            serial = root / "serial"
            first = root / "parallel-00"
            second = root / "parallel-01"
            output = root / "aggregate"
            all_rows = [row(index) for index in range(4)]
            write_output(
                serial,
                partition_count=1,
                partition_index=0,
                rows=all_rows,
                seconds=50.0,
                started=100.0,
            )
            write_output(
                first,
                partition_count=2,
                partition_index=0,
                rows=[all_rows[0], all_rows[2]],
                seconds=4.0,
                started=200.0,
            )
            write_output(
                second,
                partition_count=2,
                partition_index=1,
                rows=[all_rows[1], all_rows[3]],
                seconds=3.5,
                started=200.2,
            )
            report = aggregate_outputs(
                serial, [first, second], output, minimum_speedup=10.0
            )
            self.assertTrue(report["equivalence"]["byte_identical_outputs"])
            self.assertTrue(
                report["decision"]["pass_10x_distributed_service_throughput"]
            )
            self.assertEqual(
                report["distributed"]["service_throughput_speedup"], 12.5
            )

    def test_output_difference_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            serial = root / "serial"
            first = root / "parallel-00"
            second = root / "parallel-01"
            all_rows = [row(index) for index in range(4)]
            write_output(
                serial,
                partition_count=1,
                partition_index=0,
                rows=all_rows,
                seconds=50.0,
                started=100.0,
            )
            write_output(
                first,
                partition_count=2,
                partition_index=0,
                rows=[all_rows[0], all_rows[2]],
                seconds=4.0,
                started=200.0,
            )
            write_output(
                second,
                partition_count=2,
                partition_index=1,
                rows=[all_rows[1], row(3, "changed")],
                seconds=3.5,
                started=200.2,
            )
            with self.assertRaisesRegex(RuntimeError, "differs"):
                aggregate_outputs(
                    serial,
                    [first, second],
                    root / "aggregate",
                    minimum_speedup=10.0,
                )


if __name__ == "__main__":
    unittest.main()
