from __future__ import annotations

import copy
import unittest

from .coru_source_seal import (
    ARCHIVE_FILES,
    DATASET_ID,
    EXPECTED_FILES,
    seal,
    verify,
)


def metadata() -> dict:
    siblings = []
    for index, path in enumerate(EXPECTED_FILES):
        if path in ARCHIVE_FILES:
            size = 2_000_000_000
            siblings.append(
                {
                    "rfilename": path,
                    "lfs": {
                        "oid": "sha256:" + str(index + 1) * 64,
                        "size": size,
                    },
                }
            )
        else:
            siblings.append(
                {
                    "rfilename": path,
                    "blobId": format(index + 1, "x") * 40,
                    "size": 1000 + index,
                }
            )
    return {"sha": "a" * 40, "siblings": siblings}


class CoruSourceSealTests(unittest.TestCase):
    def test_seal_is_complete_outcome_blind_and_stable(self) -> None:
        result = seal(metadata())
        self.assertTrue(verify(result))
        self.assertEqual(result["dataset_id"], DATASET_ID)
        self.assertEqual(result["object_count"], len(EXPECTED_FILES))
        self.assertEqual(
            {row["path"] for row in result["objects"]},
            set(EXPECTED_FILES),
        )
        self.assertEqual(result["archives_downloaded"], 0)
        self.assertEqual(result["annotation_bytes_read"], 0)
        self.assertEqual(result["labels_read"], 0)
        self.assertEqual(result["dataset_rows_read"], 0)
        self.assertEqual(result["images_opened"], 0)
        self.assertFalse(result["ocr_executed"])
        self.assertFalse(result["outcomes_opened"])
        for row in result["objects"]:
            if row["path"] in ARCHIVE_FILES:
                self.assertEqual(row["identity"]["algorithm"], "sha256")
                self.assertEqual(len(row["identity"]["digest"]), 64)

    def test_mutation_breaks_replay(self) -> None:
        result = seal(metadata())
        result["images_opened"] = 1
        self.assertFalse(verify(result))

    def test_missing_expected_file_fails_closed(self) -> None:
        broken = metadata()
        broken["siblings"].pop()
        with self.assertRaisesRegex(RuntimeError, "missing expected file"):
            seal(broken)

    def test_archive_without_sha256_fails_closed(self) -> None:
        broken = metadata()
        archive = next(
            row
            for row in broken["siblings"]
            if row["rfilename"] in ARCHIVE_FILES
        )
        archive.pop("lfs")
        archive["blobId"] = "b" * 40
        archive["size"] = 2_000_000_000
        with self.assertRaisesRegex(RuntimeError, "lacks a SHA-256"):
            seal(broken)

    def test_small_archive_set_fails_closed(self) -> None:
        broken = copy.deepcopy(metadata())
        for row in broken["siblings"]:
            if row["rfilename"] in ARCHIVE_FILES:
                row["lfs"]["size"] = 1
        with self.assertRaisesRegex(RuntimeError, "unexpectedly small"):
            seal(broken)


if __name__ == "__main__":
    unittest.main()
