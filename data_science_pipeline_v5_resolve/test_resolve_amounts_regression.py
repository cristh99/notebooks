from __future__ import annotations

import unittest

from resolve_amounts_strict import resolve_amounts_strict


def line(text: str, line_no: int = 1) -> dict[str, object]:
    return {
        "text": text,
        "line_id": f"doc:page:0001:b1:p1:l{line_no}",
        "page_number": 1,
        "mean_confidence": 90.0,
        "lineage_parent_sha256": "a" * 64,
    }


class StrictAmountRegressionTests(unittest.TestCase):
    def test_fiscal_year_is_not_lempira_amount(self) -> None:
        amounts, abstentions = resolve_amounts_strict([line("EJERCICIO FISCAL 2024")])
        self.assertEqual(amounts, [])
        self.assertEqual(abstentions[0]["reason_code"], "NO_CURRENCY_QUALIFIED_AMOUNT")

    def test_explicit_lempira_marker_resolves(self) -> None:
        amounts, abstentions = resolve_amounts_strict([line("Monto: L. 1,250.00")])
        self.assertEqual([(row["currency"], row["value"]) for row in amounts], [("HNL", 1250.0)])
        self.assertEqual(abstentions, [])

    def test_suffix_currency_and_decimal_comma_resolve(self) -> None:
        amounts, _ = resolve_amounts_strict([line("Total 1.250,00 lempiras")])
        self.assertEqual(amounts[0]["currency"], "HNL")
        self.assertEqual(amounts[0]["value"], 1250.0)

    def test_phone_decree_and_page_numbers_are_not_money(self) -> None:
        amounts, abstentions = resolve_amounts_strict([
            line("Tel.: +504 2209-5355", 1),
            line("Decreto Legislativo 62-2023", 2),
            line("Página 27", 3),
        ])
        self.assertEqual(amounts, [])
        self.assertEqual(len(abstentions), 1)


if __name__ == "__main__":
    unittest.main()
