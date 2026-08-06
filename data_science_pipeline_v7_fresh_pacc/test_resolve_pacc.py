from __future__ import annotations

import unittest

from resolve_pacc import resolve_entities_pacc, resolve_years
from resolve_fresh import resolve_amounts_strict


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


class PaccResolverTests(unittest.TestCase):
    def test_pacc_acronym_resolves(self):
        entities, mentions, collisions = resolve_entities_pacc([line("Flujo del PACC 2023")])
        self.assertIn("hn:concept:pacc", {row["entity_id"] for row in entities})
        self.assertTrue(mentions)
        self.assertEqual(collisions, [])

    def test_full_pacc_name_resolves(self):
        entities, _, _ = resolve_entities_pacc([line("Plan Anual de Compras y Contrataciones")])
        self.assertIn("hn:concept:pacc", {row["entity_id"] for row in entities})

    def test_standalone_year_resolves(self):
        dates = resolve_years([line("PACC 2023")])
        self.assertTrue(any(row["value"] == "2023" and row["precision"] == "year" for row in dates))

    def test_decree_identifier_is_not_year_date_fragment(self):
        dates = resolve_years([line("Decreto 62-2023")])
        self.assertFalse(any(row["value"] == "2023" and row["precision"] == "year" for row in dates))

    def test_fiscal_year_does_not_become_money(self):
        amounts, abstentions = resolve_amounts_strict([line("EJERCICIO FISCAL 2023")])
        self.assertEqual(amounts, [])
        self.assertEqual(abstentions[0]["reason_code"], "NO_CURRENCY_QUALIFIED_AMOUNT")


if __name__ == "__main__":
    unittest.main()
