from __future__ import annotations

import unittest

from resolve_fresh import (
    parse_number,
    resolve_amounts_strict,
    resolve_dates_fresh,
    resolve_entities_fresh,
    resolve_legal_fresh,
)


def line(text: str, number: int = 1):
    return {
        "text": text,
        "line_id": f"doc:p1:l{number}",
        "page_number": 1,
        "block_num": 1,
        "paragraph_num": 1,
        "line_num": number,
        "word_count": max(1, len(text.split())),
        "mean_confidence": 90.0,
        "lineage_parent_sha256": "a" * 64,
    }


class FreshResolverTests(unittest.TestCase):
    def test_fiscal_year_is_not_lempiras(self):
        amounts, abstentions = resolve_amounts_strict([line("EJERCICIO FISCAL 2024")])
        self.assertEqual(amounts, [])
        self.assertEqual(abstentions[0]["reason_code"], "NO_CURRENCY_QUALIFIED_AMOUNT")

    def test_standalone_lempira_marker_resolves(self):
        amounts, abstentions = resolve_amounts_strict([line("Monto L 1,250.00")])
        self.assertEqual(amounts[0]["currency"], "HNL")
        self.assertEqual(amounts[0]["value"], 1250.0)
        self.assertEqual(abstentions, [])

    def test_spanish_decimal_parsing(self):
        self.assertEqual(parse_number("1.250,50"), 1250.5)

    def test_month_with_de_resolves(self):
        dates = resolve_dates_fresh([line("AGOSTO DE 2024")])
        self.assertTrue(any(row["value"] == "2024-08" for row in dates))

    def test_sesal_entity_resolves(self):
        entities, _, collisions = resolve_entities_fresh([line("Secretaría de Salud (SESAL)")])
        self.assertIn("hn:institution:sesal", {row["entity_id"] for row in entities})
        self.assertEqual(collisions, [])

    def test_pcm_resolves(self):
        instruments, _ = resolve_legal_fresh([line("Decreto PCM-053-2023")])
        self.assertIn("hn:pcm:053-2023", {row["legal_id"] for row in instruments})


if __name__ == "__main__":
    unittest.main()
