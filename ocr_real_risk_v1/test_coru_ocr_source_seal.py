from __future__ import annotations

import copy
import unittest

from .coru_ocr_source_seal import (
    COMPONENT,
    DATASET_ID,
    EXPECTED_FILES,
    seal,
    verify,
)


def metadata() -> dict:
    return {
        "sha": "a" * 40,
        "siblings": [
            {
                "rfilename": path,
                "lfs": {
                    "oid": "sha256:" + str(index + 1) * 64,
                    "size": size,
                },
            }
            for index, (path, size) in enumerate(
                zip(
                    EXPECTED_FILES,
                    (40_000_000, 190_000_000, 40_000_000),
                    strict=True,
                )
            )
        ],
    }


class CoruOcrSourceSealTests(unittest.TestCase):
    def test_seal_is_complete_outcome_blind_and_stable(self) -> None:
        result = seal(metadata())
        self.assertTrue(verify(result))
        self.assertEqual(result["dataset_id"], DATASET_ID)
        self.assertEqual(result["component"], COMPONENT)
        self.assertEqual(result["object_count"], 3)
        self.assertEqual(
            {row["path"] for row in result["objects"]},
            set(EXPECTED_FILES),
        )
        self.assertEqual(result["archives_downloaded"], 0)
        self.assertEqual(result["archive_members_listed"], 0)
        self.assertEqual(result["labels_read"], 0)
        self.assertEqual(result["images_opened"], 0)
        self.assertFalse(result["ocr_executed"])
        self.assertFalse(result["outcomes_opened"])
        self.assertTrue(all(len(row["sha256"]) == 64 for row in result["objects"]))

    def test_mutation_breaks_replay(self) -> None:
        result = seal(metadata())
        result["archive_members_listed"] = 1
        self.assertFalse(verify(result))

    def test_missing_archive_fails_closed(self) -> None:
        broken = metadata()
        broken["siblings"].pop()
        with self.assertRaisesRegex(RuntimeError, "missing expected file"):
            seal(broken)

    def test_missing_sha256_fails_closed(self) -> None:
        broken = metadata()
        broken["siblings"][0]["lfs"].pop("oid")
        with self.assertRaisesRegex(RuntimeError, "lacks SHA-256"):
            seal(broken)

    def test_small_archive_set_fails_closed(self) -> None:
        broken = copy.deepcopy(metadata())
        for row in broken["siblings"]:
            row["lfs"]["size"] = 1
        with self.assertRaisesRegex(RuntimeError, "unexpectedly small"):
            seal(broken)


if __name__ == "__main__":
    unittest.main()
