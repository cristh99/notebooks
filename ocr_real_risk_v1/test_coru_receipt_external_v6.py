from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from .coru_receipt_external_v6 import (
    exact_summary,
    normalized_member_name,
    partition_id,
    resolve_image_members,
    safe_image_members,
)


def selected(filename: str, annotation_id: str = "1") -> dict:
    return {
        "image_id": filename,
        "filename": filename,
        "annotation_id": annotation_id,
        "truth": "1234",
        "bbox_xyxy": [1.0, 2.0, 20.0, 10.0],
        "selection_rank_sha256": "a" * 64,
    }


def observation(
    *,
    baseline_correct: bool = True,
    accepted: bool = False,
    false_accept: bool = False,
    counterfactual_collision: bool = False,
) -> dict:
    return {
        "baseline": {
            "eligible": True,
            "claim_correct": baseline_correct,
        },
        "candidate": {
            "accepted": accepted,
            "false_accept": false_accept,
            "counterfactual_output_collision": counterfactual_collision,
        },
    }


class CoruReceiptExternalV6Tests(unittest.TestCase):
    def test_member_names_fail_closed(self) -> None:
        for value in ("", "../x.jpg", "/x.jpg", "folder\\x.jpg"):
            with self.assertRaises(RuntimeError):
                normalized_member_name(value)
        self.assertEqual(
            normalized_member_name("images/x.jpg"), "images/x.jpg"
        )

    def test_exact_and_unique_basename_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "images.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("images/a.jpg", b"a")
                archive.writestr("nested/b.png", b"b")
                archive.writestr("notes.txt", b"ignored")
            members = safe_image_members(path)
            resolved = resolve_image_members(
                [selected("images/a.jpg"), selected("b.png", "2")],
                members,
            )
            self.assertEqual(len(resolved), 2)
            by_filename = {row["filename"]: row for row in resolved}
            self.assertEqual(
                by_filename["images/a.jpg"]["archive_resolution"],
                "exact_path",
            )
            self.assertEqual(
                by_filename["b.png"]["archive_resolution"],
                "unique_basename",
            )
            self.assertEqual(
                by_filename["b.png"]["archive_member"], "nested/b.png"
            )

    def test_ambiguous_basename_and_duplicate_resolution_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "images.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("a/x.jpg", b"a")
                archive.writestr("b/x.jpg", b"b")
            members = safe_image_members(path)
            with self.assertRaisesRegex(RuntimeError, "missing or ambiguous"):
                resolve_image_members([selected("x.jpg")], members)
            with self.assertRaisesRegex(RuntimeError, "one archive image"):
                resolve_image_members(
                    [selected("a/x.jpg", "1"), selected("a/x.jpg", "2")],
                    members,
                )

    def test_partition_is_deterministic_and_bounded(self) -> None:
        record = selected("images/a.jpg")
        first = partition_id(record, 12)
        second = partition_id(dict(record), 12)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 12)
        with self.assertRaises(ValueError):
            partition_id(record, 0)

    def test_exact_gate_requires_population_coverage_and_safety(self) -> None:
        rows = []
        for index in range(3000):
            rows.append(
                observation(
                    baseline_correct=index >= 500,
                    accepted=500 <= index < 1500,
                )
            )
        result = exact_summary(rows)
        self.assertEqual(result["selected"], 3000)
        self.assertEqual(result["baseline_false"], 500)
        self.assertEqual(result["accepted"], 1000)
        self.assertEqual(result["accepted_false"], 0)
        self.assertEqual(result["counterfactual_false"], 0)
        self.assertTrue(result["pass"])

        rows[1499]["candidate"]["false_accept"] = True
        unsafe = exact_summary(rows)
        self.assertEqual(unsafe["accepted_false"], 1)
        self.assertFalse(unsafe["pass"])


if __name__ == "__main__":
    unittest.main()
