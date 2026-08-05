from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from .coru_ocr_archive import (
    canonical_numeric_label,
    discover_pairs,
    normalized_member_name,
)


def make_zip(path: Path, files: dict[str, bytes | str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            data = value.encode("utf-8") if isinstance(value, str) else value
            archive.writestr(name, data)


class CoruOcrArchiveTests(unittest.TestCase):
    def test_numeric_normalization_handles_unicode_and_rejects_years(self) -> None:
        self.assertEqual(canonical_numeric_label("$ ١٢,٣٤٥.٦٧"), "1234567")
        self.assertEqual(canonical_numeric_label("12 34"), "1234")
        self.assertIsNone(canonical_numeric_label("2024"))
        self.assertIsNone(canonical_numeric_label("1111"))
        self.assertIsNone(canonical_numeric_label("AB12,345"))
        self.assertIsNone(canonical_numeric_label("123"))
        self.assertIsNone(canonical_numeric_label("1234567890123"))

    def test_unsafe_member_names_fail_closed(self) -> None:
        for name in ("../evil.png", "/absolute.png", "folder\\evil.png", ""):
            with self.assertRaises(RuntimeError):
                normalized_member_name(name)

    def test_same_stem_gt_files_pair_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.zip"
            make_zip(
                path,
                {
                    "images/0001.png": b"not-an-image-yet",
                    "images/0001.gt.txt": "12,345",
                    "images/0002.jpg": b"not-an-image-yet",
                    "images/0002.gt.txt": "TOTAL",
                },
            )
            result = discover_pairs(path)
            self.assertEqual(result["image_count"], 2)
            self.assertEqual(result["pair_count"], 2)
            self.assertEqual(result["numeric_pair_count"], 1)
            self.assertEqual(
                result["numeric_pairs"][0]["canonical_numeric_label"],
                "12345",
            )
            self.assertEqual(
                result["label_sources"],
                {"same_stem_label_file": 2},
            )

    def test_json_manifest_pairs_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.zip"
            make_zip(
                path,
                {
                    "images/a.png": b"x",
                    "images/b.png": b"y",
                    "annotations.json": json.dumps(
                        {
                            "records": [
                                {"file_name": "images/a.png", "text": "9,876"},
                                {"file_name": "images/b.png", "text": "hello"},
                            ]
                        }
                    ),
                },
            )
            result = discover_pairs(path)
            self.assertEqual(result["pair_count"], 2)
            self.assertEqual(result["numeric_pair_count"], 1)
            self.assertEqual(result["label_sources"], {"json_record": 2})

    def test_tab_manifest_pairs_by_basename_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.zip"
            make_zip(
                path,
                {
                    "test/images/a.png": b"x",
                    "test/images/b.png": b"y",
                    "test/labels.tsv": "a.png\t12 345\nb.png\tTEXT\n",
                },
            )
            result = discover_pairs(path)
            self.assertEqual(result["pair_count"], 2)
            self.assertEqual(result["numeric_pair_count"], 1)
            self.assertEqual(result["label_sources"], {"delimited_line": 2})

    def test_double_underscore_filename_is_last_resort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.zip"
            make_zip(
                path,
                {
                    "0001__12,345.png": b"x",
                    "0002__HELLO.jpg": b"y",
                },
            )
            result = discover_pairs(path)
            self.assertEqual(result["pair_count"], 2)
            self.assertEqual(result["numeric_pair_count"], 1)
            self.assertEqual(
                result["label_sources"],
                {"double_underscore_filename_label": 2},
            )

    def test_conflicting_explicit_labels_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.zip"
            make_zip(
                path,
                {
                    "images/a.png": b"x",
                    "images/a.gt.txt": "12345",
                    "annotations.tsv": "images/a.png\t54321\n",
                },
            )
            with self.assertRaisesRegex(RuntimeError, "conflicting explicit labels"):
                discover_pairs(path)

    def test_unresolved_labels_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.zip"
            make_zip(path, {"images/a.png": b"x"})
            with self.assertRaisesRegex(RuntimeError, "unresolved image labels"):
                discover_pairs(path)


if __name__ == "__main__":
    unittest.main()
