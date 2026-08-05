from __future__ import annotations

import copy
import unittest

from .wildreceipt_source_seal import DATASET_ID, seal, verify


def metadata() -> dict:
    return {
        "sha": "a" * 40,
        "siblings": [
            {
                "rfilename": "wildreceipt.tar",
                "lfs": {"sha256": "1" * 64, "size": 60_000_000},
            },
            {
                "rfilename": "wildreceipt.py",
                "lfs": {"oid": "sha256:" + "2" * 64, "size": 20_000},
            },
            {"rfilename": "README.md", "size": 100},
        ],
    }


class WildReceiptSourceSealTests(unittest.TestCase):
    def test_seal_is_outcome_blind_and_stable(self) -> None:
        result = seal(metadata())
        self.assertTrue(verify(result))
        self.assertEqual(result["dataset_id"], DATASET_ID)
        self.assertEqual(result["dataset_rows_read"], 0)
        self.assertEqual(result["images_opened"], 0)
        self.assertEqual(result["annotations_opened"], 0)
        self.assertFalse(result["ocr_executed"])
        self.assertEqual(result["object_count"], 2)

    def test_mutation_breaks_replay(self) -> None:
        result = seal(metadata())
        result["dataset_rows_read"] = 1
        self.assertFalse(verify(result))

    def test_missing_hash_fails_closed(self) -> None:
        broken = metadata()
        broken["siblings"][0]["lfs"].pop("sha256")
        with self.assertRaises(RuntimeError):
            seal(broken)

    def test_small_repository_fails_closed(self) -> None:
        broken = copy.deepcopy(metadata())
        broken["siblings"][0]["lfs"]["size"] = 1
        with self.assertRaises(RuntimeError):
            seal(broken)


if __name__ == "__main__":
    unittest.main()
