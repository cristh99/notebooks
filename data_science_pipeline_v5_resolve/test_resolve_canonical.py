from __future__ import annotations

import unittest

import resolve_canonical as base
from resolve_runner import resolve_legal_with_original_punctuation


def line(text: str, line_no: int = 1, confidence: float = 90.0):
    return {
        "text": text,
        "line_id": f"doc:page:0001:b1:p1:l{line_no}",
        "page_number": 1,
        "block_num": 1,
        "paragraph_num": 1,
        "line_num": line_no,
        "word_count": max(1, len(text.split())),
        "mean_confidence": confidence,
        "lineage_parent_sha256": "a" * 64,
    }


class ResolveTests(unittest.TestCase):
    def test_registry_collision_fails_closed(self):
        with self.assertRaises(RuntimeError):
            base.validate_registry((
                {"id": "a", "aliases": ("same",)},
                {"id": "b", "aliases": ("same",)},
            ), "id")

    def test_oncae_acronym_resolves(self):
        entities, mentions, collisions = base.resolve_entities([line("(ONCAE)")])
        self.assertIn("hn:institution:oncae", {item["entity_id"] for item in entities})
        self.assertEqual(len(mentions), 1)
        self.assertFalse(collisions)

    def test_month_year_resolves(self):
        dates = base.resolve_dates([line("NOVIEMBRE 2024")])
        self.assertEqual(dates[0]["value"], "2024-11")
        self.assertEqual(dates[0]["precision"], "month")

    def test_decree_preserves_hyphen(self):
        instruments, mentions = resolve_legal_with_original_punctuation([
            line("DECRETOS LEGISLATIVOS 62-2023", 1),
        ])
        self.assertIn("hn:decree:62-2023", {item["legal_id"] for item in instruments})
        self.assertTrue(any(item["surface_text"].endswith("62-2023") for item in mentions))

    def test_unqualified_numbers_are_not_money(self):
        amounts, abstentions = base.resolve_amounts([
            line("NOVIEMBRE 2024", 1),
            line("página 27", 2),
            line("Decreto 62-2023", 3),
        ])
        self.assertFalse(amounts)
        self.assertEqual(abstentions[0]["reason_code"], "NO_CURRENCY_QUALIFIED_AMOUNT")

    def test_explicit_money_resolves(self):
        amounts, abstentions = base.resolve_amounts([line("Monto: L 1,250.00")])
        self.assertEqual(amounts[0]["currency"], "HNL")
        self.assertEqual(amounts[0]["value"], 1250.0)
        self.assertFalse(abstentions)

    def test_phone_resolves_canonically(self):
        contacts = base.resolve_contacts([line("Tel.: +504 2209-5355")])
        self.assertEqual(contacts[0]["canonical_value"], "+504-2209-5355")


if __name__ == "__main__":
    unittest.main()
