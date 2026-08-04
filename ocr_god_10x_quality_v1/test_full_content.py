from __future__ import annotations

import unittest

from .full_content_quality import (
    counter_metrics,
    html_to_plain,
    latex_to_plain,
    newly_valid_count,
    number_tokens,
    page_reference,
    word_tokens,
)


class FullContentMetricTests(unittest.TestCase):
    def test_html_table_cells_become_visible_text(self) -> None:
        value = html_to_plain(
            "<table><tr><td>Revenue</td><td>98,765.43</td></tr></table>"
        )
        self.assertIn("Revenue", value)
        self.assertIn("98,765.43", value)

    def test_latex_keeps_arguments_not_commands(self) -> None:
        value = latex_to_plain(r"$\frac{104729}{7}+\mathrm{HNL}$")
        self.assertIn("104729", value)
        self.assertIn("7", value)
        self.assertIn("HNL", value)
        self.assertNotIn("frac", value)
        self.assertNotIn("mathrm", value)

    def test_prior_false_positive_can_be_reclassified(self) -> None:
        old = word_tokens("Revenue")
        full = word_tokens("Revenue 98,765.43")
        pred = word_tokens("Revenue 98,765.43")
        self.assertGreater(newly_valid_count(old, full, pred), 0)
        self.assertEqual(counter_metrics(full, pred)["f1"], 1.0)

    def test_table_and_formula_enter_page_reference(self) -> None:
        raw = {
            "layout_dets": [
                {
                    "anno_id": 1,
                    "order": 0,
                    "category_type": "text_block",
                    "text": "Balance sheet",
                    "ignore": False,
                },
                {
                    "anno_id": 2,
                    "order": 1,
                    "category_type": "table",
                    "html": "<table><tr><td>Assets</td><td>100</td></tr></table>",
                    "ignore": False,
                },
                {
                    "anno_id": 3,
                    "order": 2,
                    "category_type": "equation_isolated",
                    "latex": r"$A=L+E$",
                    "ignore": False,
                },
            ],
            "extra": {"relation": []},
        }
        ref = page_reference(raw)
        self.assertIn("Balance sheet", ref["text"])
        self.assertIn("Assets", ref["table"])
        self.assertIn("A", ref["formula"])
        self.assertIn("100", number_tokens(ref["full"]))


if __name__ == "__main__":
    unittest.main()
