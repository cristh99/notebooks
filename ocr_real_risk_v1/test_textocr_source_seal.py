from __future__ import annotations

import copy
import unittest

from .textocr_source_seal import (
    COMPONENT,
    DATASET_ID,
    MAXIMUM_SOURCE_BYTES,
    MINIMUM_SOURCE_BYTES,
    seal,
    verify,
)


def metadata() -> dict:
    return {
        "sha": "a" * 40,
        "siblings": [
            {
                "rfilename": "data/TextOCR-00000-of-00001.parquet",
                "lfs": {
                    "oid": "sha256:" + "b" * 64,
                    "size": 6_200_000_000,
                },
            },
            {
                "rfilename": "data/ART-00000-of-00001.parquet",
                "lfs": {
                    "oid": "sha256:" + "c" * 64,
                    "size": 1_500_000_000,
                },
            },
        ],
    }


class TextOcrSourceSealTests(unittest.TestCase):
    def test_seal_is_stable_complete_and_outcome_blind(self) -> None:
        result = seal(metadata())
        self.assertTrue(verify(result))
        self.assertEqual(result["dataset_id"], DATASET_ID)
        self.assertEqual(result["component"], COMPONENT)
        self.assertEqual(
            result["source_object"]["path"],
            "data/TextOCR-00000-of-00001.parquet",
        )
        self.assertEqual(result["source_object"]["sha256"], "b" * 64)
        self.assertEqual(result["source_object"]["size_bytes"], 6_200_000_000)
        self.assertTrue(result["repository_metadata_only"])
        self.assertFalse(result["parquet_footer_read"])
        self.assertEqual(result["parquet_bytes_downloaded"], 0)
        self.assertEqual(result["dataset_rows_read"], 0)
        self.assertEqual(result["texts_opened"], 0)
        self.assertEqual(result["bounding_boxes_opened"], 0)
        self.assertEqual(result["polygons_opened"], 0)
        self.assertEqual(result["images_opened"], 0)
        self.assertFalse(result["ocr_executed"])
        self.assertFalse(result["candidate_inference_executed"])
        self.assertFalse(result["outcomes_opened"])
        self.assertTrue(
            result["licenses"]["upstream_terms_take_precedence"]
        )

    def test_mutation_breaks_stable_replay(self) -> None:
        result = seal(metadata())
        result["dataset_rows_read"] = 1
        self.assertFalse(verify(result))

    def test_missing_or_duplicate_textocr_object_fails_closed(self) -> None:
        missing = metadata()
        missing["siblings"] = missing["siblings"][1:]
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            seal(missing)

        duplicate = metadata()
        duplicate["siblings"].append(
            {
                "rfilename": "data/TextOCR-copy.parquet",
                "lfs": {
                    "oid": "sha256:" + "d" * 64,
                    "size": 6_000_000_000,
                },
            }
        )
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            seal(duplicate)

    def test_missing_sha256_and_implausible_size_fail_closed(self) -> None:
        no_hash = metadata()
        no_hash["siblings"][0]["lfs"].pop("oid")
        with self.assertRaisesRegex(RuntimeError, "lacks SHA-256"):
            seal(no_hash)

        too_small = copy.deepcopy(metadata())
        too_small["siblings"][0]["lfs"]["size"] = MINIMUM_SOURCE_BYTES - 1
        with self.assertRaisesRegex(RuntimeError, "implausible"):
            seal(too_small)

        too_large = copy.deepcopy(metadata())
        too_large["siblings"][0]["lfs"]["size"] = MAXIMUM_SOURCE_BYTES + 1
        with self.assertRaisesRegex(RuntimeError, "implausible"):
            seal(too_large)

    def test_non_full_revision_fails_closed(self) -> None:
        broken = metadata()
        broken["sha"] = "abc"
        with self.assertRaisesRegex(RuntimeError, "full commit SHA"):
            seal(broken)


if __name__ == "__main__":
    unittest.main()
