from __future__ import annotations

import base64
import contextlib
import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import openvino_motherduck_flight_v7 as portable


class OpenVinoMotherDuckFlightV7Tests(unittest.TestCase):
    def test_frozen_candidate_replays_exactly(self) -> None:
        candidate = portable.frozen_candidate()
        self.assertEqual(
            candidate["stable_payload_sha256"],
            portable.CANDIDATE_STABLE_SHA256,
        )
        self.assertEqual(candidate["source_commit"], portable.FROZEN_SOURCE_COMMIT)
        self.assertEqual(
            candidate["metadata_power_gate"]["expected_source_rows"],
            portable.EXPECTED_SOURCE_ROWS,
        )
        self.assertFalse(
            candidate["metadata_power_gate"][
                "full_image_download_authorized_in_this_gate"
            ]
        )

    def test_pinned_source_receipts_match_repository_copy(self) -> None:
        root = Path(__file__).resolve().parent
        for name, expected in portable.SOURCE_FILES.items():
            raw = (root / name).read_bytes()
            self.assertEqual(len(raw), expected["bytes"], name)
            self.assertEqual(portable.sha256_bytes(raw), expected["sha256"], name)
            self.assertEqual(
                portable.git_blob_sha1(raw), expected["git_blob_sha1"], name
            )

    def test_materialized_package_imports_only_pinned_scientific_modules(
        self,
    ) -> None:
        root = Path(__file__).resolve().parent

        def fake_fetch(url: str, *, timeout: float = 120.0) -> bytes:
            del timeout
            return (root / url.rsplit("/", 1)[-1]).read_bytes()

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "frozen"
            with mock.patch.object(portable, "_fetch", side_effect=fake_fetch):
                receipt = portable.materialize_frozen_package(target)
            _, source_seal, adapter, terminal = portable.load_frozen_modules(
                target
            )
            self.assertEqual(set(portable.SOURCE_FILES), set(receipt) - {
                "sroie_natural_holdout.py"
            })
            self.assertEqual(adapter.EXPECTED_ROW_COUNT, 207_790)
            self.assertEqual(
                adapter.REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS, 16_997
            )
            self.assertTrue(callable(source_seal.seal))
            self.assertTrue(callable(terminal.adjudicate))

    def test_compact_census_removes_records_but_preserves_hash(self) -> None:
        report = {
            "exact_census": {
                "selected_count": 2,
                "selected_record_set_sha256": "a" * 64,
                "records": [{"row_index": 1}, {"row_index": 2}],
            },
            "stable_payload_sha256": "b" * 64,
        }
        compact = portable.compact_census(report)
        self.assertNotIn("records", compact["exact_census"])
        self.assertEqual(
            compact["exact_census"]["selected_record_set_sha256"], "a" * 64
        )
        self.assertIn("records", report["exact_census"])

    def test_emitted_artifact_round_trips(self) -> None:
        payload = {"a": 1, "b": [2, 3]}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            receipt = portable.emit_json_artifact("TEST", payload)
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "BEGIN_TEST_GZIP_BASE64")
        self.assertEqual(lines[-1], "END_TEST_GZIP_BASE64")
        raw = gzip.decompress(base64.b64decode(lines[1]))
        self.assertEqual(json.loads(raw), payload)
        self.assertEqual(portable.sha256_bytes(raw), receipt["raw_sha256"])


if __name__ == "__main__":
    unittest.main()
