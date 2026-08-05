from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .sroie_official_canary_v4 import (
    BoxToken,
    Match,
    Scope,
    canonical_numeric,
    classify_scope,
    match_geometry_only,
    parse_truth,
)


class SroieOfficialCanaryV4Tests(unittest.TestCase):
    def test_numeric_scope_is_ascii_and_bounded(self) -> None:
        self.assertEqual(canonical_numeric("HNL 1,234.50"), "123450")
        self.assertIsNone(canonical_numeric("١٢٣٤"))
        self.assertIsNone(canonical_numeric("123"))
        self.assertIsNone(canonical_numeric("abc1234"))

    def test_parse_official_polygon_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.txt"
            path.write_text(
                "10,20,50,20,50,40,10,40,RM 1,234.50\n"
                "1,2,3\n",
                encoding="utf-8",
            )
            rows = parse_truth(path, "page")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].digits, "123450")
        self.assertEqual(rows[0].bbox, (10.0, 20.0, 50.0, 40.0))

    def test_geometry_matching_does_not_consult_token_text(self) -> None:
        candidates = [
            BoxToken("p", "c", "9999", "9999", (10, 10, 50, 30), 90.0),
        ]
        truth = [
            BoxToken("p", "t", "1234", "1234", (11, 9, 51, 31), None),
        ]
        matches = match_geometry_only(candidates, truth)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].candidate.digits, "9999")
        self.assertEqual(matches[0].truth.digits, "1234")

    def test_length_mismatch_is_outside_substitution_scope(self) -> None:
        match = Match(
            candidate=BoxToken("p", "c", "07-355", "07355", (0, 0, 50, 20), 80.0),
            truth=BoxToken("p", "t", "07-355 2616", "073552616", (0, 0, 100, 20), None),
            geometry_score=0.9,
            iou=0.5,
            smaller_coverage=1.0,
            vertical_overlap=1.0,
        )
        self.assertEqual(classify_scope(match), Scope.OUT_OF_SCOPE_LENGTH_OR_PARTIAL_MATCH)

    def test_same_length_is_the_only_visual_substitution_scope(self) -> None:
        match = Match(
            candidate=BoxToken("p", "c", "112.46", "11246", (0, 0, 50, 20), 47.0),
            truth=BoxToken("p", "t", "112.45", "11245", (0, 0, 50, 20), None),
            geometry_score=1.0,
            iou=1.0,
            smaller_coverage=1.0,
            vertical_overlap=1.0,
        )
        self.assertEqual(classify_scope(match), Scope.SAME_LENGTH_SUBSTITUTION)


if __name__ == "__main__":
    unittest.main()
