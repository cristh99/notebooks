from __future__ import annotations

import unittest

from .core import Candidate
from .evaluate_dual_anchor import (
    canonical_dual_truth,
    filter_words_by_anchor,
    prepare_process_disjoint_candidates,
    quantile_pages,
)


def candidate(
    url: str,
    process: str,
    document_type: str,
    institution: str = "INST-A",
) -> Candidate:
    return Candidate(
        url=url,
        document_type=document_type,
        process=process,
        ocid=f"ocds-{process}",
        institution_code=institution,
        institution_name=institution,
        source_year=2025,
        source_line=1,
    )


class DualAnchorEvaluationTests(unittest.TestCase):
    def test_filter_preserves_page_word_count_and_blanks_only_unanchored_numbers(self) -> None:
        words = [
            {"text": "Proyecto", "bbox_pt": [0, 0, 10, 10]},
            {"text": "110509", "bbox_pt": [11, 0, 20, 10]},
            {"text": "987654", "bbox_pt": [21, 0, 30, 10]},
            {"text": "2025", "bbox_pt": [31, 0, 40, 10]},
        ]
        filtered, counts = filter_words_by_anchor(words, {"110509"})
        self.assertEqual(len(filtered), len(words))
        self.assertEqual(filtered[0]["text"], "Proyecto")
        self.assertEqual(filtered[1]["text"], "110509")
        self.assertEqual(filtered[2]["text"], "")
        # Years are outside the measured truth protocol and remain irrelevant
        # without being counted as an anchor rejection.
        self.assertEqual(filtered[3]["text"], "2025")
        self.assertEqual(counts["anchored_numeric_words"], 1)
        self.assertEqual(counts["unanchored_numeric_words_excluded"], 1)
        self.assertEqual(counts["non_numeric_words_preserved"], 2)

    def test_repeated_digit_junk_never_enters_anchor_rejection_counts(self) -> None:
        filtered, counts = filter_words_by_anchor(
            [{"text": "999999"}],
            set(),
        )
        self.assertEqual(filtered[0]["text"], "999999")
        self.assertEqual(counts["non_numeric_words_preserved"], 1)
        self.assertEqual(counts["unanchored_numeric_words_excluded"], 0)

    def test_grouped_amounts_are_normalized_only_inside_declared_scope(self) -> None:
        self.assertEqual(canonical_dual_truth("L. 1,200.50"), "120050")
        self.assertEqual(canonical_dual_truth("1.200,50"), "120050")
        self.assertEqual(canonical_dual_truth("1234.50"), "123450")
        self.assertIsNone(canonical_dual_truth("2025"))
        self.assertIsNone(canonical_dual_truth("000-001-01-00000524"))
        self.assertIsNone(canonical_dual_truth("999999"))

    def test_grouped_amount_is_replaced_by_canonical_anchored_digits(self) -> None:
        filtered, counts = filter_words_by_anchor(
            [{"text": "L.1,200.50"}],
            {"120050"},
        )
        self.assertEqual(filtered[0]["text"], "120050")
        self.assertEqual(counts["anchored_numeric_words"], 1)

    def test_empty_anchor_set_removes_all_eligible_numeric_truths(self) -> None:
        words = [
            {"text": "108919"},
            {"text": "texto"},
            {"text": "2024"},
        ]
        filtered, counts = filter_words_by_anchor(words, set())
        self.assertEqual(
            [row["text"] for row in filtered],
            ["", "texto", "2024"],
        )
        self.assertEqual(counts["unanchored_numeric_words_excluded"], 1)

    def test_quantile_pages_are_predeclared_and_cover_document(self) -> None:
        self.assertEqual(quantile_pages(4), (1, 2, 3, 4))
        pages = quantile_pages(100, maximum_pages=8)
        self.assertEqual(len(pages), 8)
        self.assertEqual(pages[0], 1)
        self.assertEqual(pages[-1], 100)
        self.assertEqual(pages, tuple(sorted(set(pages))))

    def test_one_born_digital_document_is_selected_per_process(self) -> None:
        values = [
            candidate(
                "https://example.test/contract.pdf",
                "P1",
                "contractSigned",
            ),
            candidate(
                "https://example.test/notice.pdf",
                "P1",
                "tenderNotice",
            ),
            candidate(
                "https://example.test/bid.pdf",
                "P1",
                "biddingDocuments",
            ),
            candidate(
                "https://example.test/amendment.pdf",
                "P2",
                "amendment",
            ),
        ]
        selected, census = prepare_process_disjoint_candidates(values)
        self.assertEqual(len(selected), 2)
        self.assertEqual(
            {row.process: row.document_type for row in selected},
            {"P1": "biddingDocuments", "P2": "amendment"},
        )
        self.assertEqual(census["excluded_out_of_vector_truth_scope"], 1)
        self.assertFalse(census["selection_uses_ocr"])


if __name__ == "__main__":
    unittest.main()
