from __future__ import annotations

import unittest

from .cord_source_seal import EXPECTED_FILES, EXPECTED_ROWS, seal, verify


class CordSourceSealTests(unittest.TestCase):
    def _metadata(self):
        return {
            "sha": "a" * 40,
            "siblings": [
                {
                    "rfilename": path,
                    "lfs": {
                        "oid": "sha256:" + format(index + 1, "064x"),
                        "size": 1000 + index,
                    },
                }
                for index, path in enumerate(EXPECTED_FILES)
            ],
        }

    def test_seal_is_stable_and_outcome_blind(self) -> None:
        result = seal(self._metadata())
        self.assertTrue(verify(result))
        self.assertEqual(result["resolved_revision"], "a" * 40)
        self.assertEqual(result["expected_rows"], EXPECTED_ROWS)
        self.assertEqual(result["expected_total_rows"], 1000)
        self.assertEqual(len(result["files"]), 6)
        self.assertFalse(result["outcomes_opened"])
        self.assertEqual(result["parquet_rows_read"], 0)

    def test_missing_file_fails_closed(self) -> None:
        metadata = self._metadata()
        metadata["siblings"].pop()
        with self.assertRaisesRegex(RuntimeError, "missing expected dataset file"):
            seal(metadata)

    def test_missing_lfs_hash_fails_closed(self) -> None:
        metadata = self._metadata()
        metadata["siblings"][0]["lfs"].pop("oid")
        with self.assertRaisesRegex(RuntimeError, "missing SHA-256 LFS oid"):
            seal(metadata)

    def test_mutation_breaks_replay(self) -> None:
        result = seal(self._metadata())
        result["expected_total_rows"] = 999
        self.assertFalse(verify(result))


if __name__ == "__main__":
    unittest.main()
