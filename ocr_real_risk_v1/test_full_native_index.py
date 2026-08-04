from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .evaluate_dual_anchor import canonical_dual_truth
from .full_native_index import (
    IndexedPage,
    isolate_selected_location,
    parse_bbox_document,
    select_dual_anchored_location,
)


def words_with_numeric(
    value: str,
    bbox: tuple[float, float, float, float],
    count: int = 25,
) -> tuple[dict[str, object], ...]:
    words: list[dict[str, object]] = [
        {"text": f"word-{index}", "bbox_pt": [index, 1, index + 0.8, 2]}
        for index in range(count - 1)
    ]
    words.append({"text": value, "bbox_pt": list(bbox)})
    return tuple(words)


class FullNativeIndexTests(unittest.TestCase):
    def test_parse_two_page_bbox_document(self) -> None:
        payload = """<?xml version='1.0' encoding='UTF-8'?>
        <html xmlns='http://www.w3.org/1999/xhtml'><body><doc>
          <page width='600' height='800'>
            <flow><block><line>
              <word xMin='10' yMin='20' xMax='50' yMax='35'>110509</word>
            </line></block></flow>
          </page>
          <page width='612' height='792'>
            <flow><block><line>
              <word xMin='15' yMin='25' xMax='55' yMax='40'>9158922.75</word>
            </line></block></flow>
          </page>
        </doc></body></html>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bbox.html"
            path.write_text(payload, encoding="utf-8")
            pages = parse_bbox_document(path)
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].page_number, 1)
        self.assertEqual(pages[1].width_pt, 612.0)
        self.assertEqual(pages[0].words[0]["text"], "110509")

    def test_selection_searches_all_pages_not_only_quantiles(self) -> None:
        pages = [
            IndexedPage(
                page_number=index,
                width_pt=600,
                height_pt=800,
                words=words_with_numeric(
                    "110509" if index == 37 else "987654",
                    (10, 20, 60, 35),
                ),
            )
            for index in range(1, 101)
        ]
        selected, metrics = select_dual_anchored_location(
            "source-sha",
            pages,
            {"110509"},
            canonical_dual_truth,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected["page_number"], 37)
        self.assertEqual(metrics["pages_indexed"], 100)
        self.assertEqual(metrics["dual_candidate_locations"], 1)

    def test_selection_is_stable_under_page_and_word_reordering(self) -> None:
        first = IndexedPage(
            3,
            600,
            800,
            words_with_numeric("110509", (10, 20, 60, 35)),
        )
        second = IndexedPage(
            9,
            600,
            800,
            words_with_numeric("120050", (15, 40, 70, 55)),
        )
        forward, _ = select_dual_anchored_location(
            "source-sha",
            [first, second],
            {"110509", "120050"},
            canonical_dual_truth,
        )
        reversed_pages = [
            IndexedPage(
                second.page_number,
                second.width_pt,
                second.height_pt,
                tuple(reversed(second.words)),
            ),
            IndexedPage(
                first.page_number,
                first.width_pt,
                first.height_pt,
                tuple(reversed(first.words)),
            ),
        ]
        reverse, _ = select_dual_anchored_location(
            "source-sha",
            reversed_pages,
            {"110509", "120050"},
            canonical_dual_truth,
        )
        self.assertEqual(forward, reverse)

    def test_low_native_word_page_is_excluded(self) -> None:
        page = IndexedPage(
            1,
            600,
            800,
            words_with_numeric("110509", (10, 20, 60, 35), count=10),
        )
        selected, metrics = select_dual_anchored_location(
            "source-sha",
            [page],
            {"110509"},
            canonical_dual_truth,
        )
        self.assertIsNone(selected)
        self.assertEqual(metrics["pages_below_native_word_floor"], 1)
        self.assertEqual(metrics["numeric_words_in_scope"], 0)

    def test_only_selected_numeric_location_survives_for_ocr(self) -> None:
        page = IndexedPage(
            4,
            600,
            800,
            tuple(
                [
                    {"text": "110509", "bbox_pt": [10, 20, 60, 35]},
                    {"text": "120050", "bbox_pt": [70, 20, 120, 35]},
                ]
                + [
                    {"text": f"word-{index}", "bbox_pt": [index, 1, index + 0.8, 2]}
                    for index in range(23)
                ]
            ),
        )
        selected, _ = select_dual_anchored_location(
            "source-sha",
            [page],
            {"110509", "120050"},
            canonical_dual_truth,
        )
        isolated = isolate_selected_location(
            page,
            selected,
            canonical_dual_truth,
        )
        surviving = [
            canonical_dual_truth(str(word["text"]))
            for word in isolated
            if canonical_dual_truth(str(word["text"])) is not None
        ]
        self.assertEqual(surviving, [selected["truth"]])
        self.assertEqual(len(isolated), len(page.words))


if __name__ == "__main__":
    unittest.main()
