from __future__ import annotations

import unittest
from amount_date_candidates import NumericClass, classify_line

def line(text: str) -> dict:
    return {
        "line_id": "p1:l1",
        "page_number": 1,
        "text": text,
        "mean_confidence": 97.5,
        "lineage_parent_sha256": "a" * 64,
    }

def classes(text: str):
    return [(c.semantic_class, c.normalized_value, c.currency) for c in classify_line(line(text))]

class NumericCandidateTests(unittest.TestCase):
    def test_fiscal_year_not_money(self):
        got = classes("EJERCICIO FISCAL 2024")
        self.assertIn((NumericClass.FISCAL_PERIOD, "2024", None), got)
        self.assertNotIn(NumericClass.MONETARY_AMOUNT, [x[0] for x in got])

    def test_iso_date_beats_phone(self):
        got = classes("Fecha 2024-11-10")
        self.assertIn((NumericClass.CALENDAR_DATE, "2024-11-10", None), got)
        self.assertNotIn(NumericClass.TELEPHONE_CONTACT, [x[0] for x in got])

    def test_dmy_hyphen_date_beats_phone(self):
        got = classes("Fecha 10-11-2020")
        self.assertIn((NumericClass.CALENDAR_DATE, "2020-11-10", None), got)
        self.assertNotIn(NumericClass.TELEPHONE_CONTACT, [x[0] for x in got])

    def test_slash_date(self):
        self.assertIn((NumericClass.CALENDAR_DATE, "2020-11-10", None), classes("10/11/2020"))

    def test_invalid_date_fails_closed(self):
        got = classes("Fecha 31-02-2024")
        self.assertNotIn(NumericClass.CALENDAR_DATE, [x[0] for x in got])
        self.assertIn(NumericClass.UNRESOLVED_NUMERIC, [x[0] for x in got])

    def test_dotted_short_date_not_money(self):
        got = classes("10.11.20")
        self.assertNotIn(NumericClass.MONETARY_AMOUNT, [x[0] for x in got])
        self.assertIn(NumericClass.UNRESOLVED_NUMERIC, [x[0] for x in got])

    def test_phone(self):
        got = classes("TELÉFONO +504 2209-5355")
        self.assertIn((NumericClass.TELEPHONE_CONTACT, "+50422095355", None), got)
        self.assertNotIn(NumericClass.CALENDAR_DATE, [x[0] for x in got])
        self.assertNotIn(NumericClass.MONETARY_AMOUNT, [x[0] for x in got])

    def test_legal_id_requires_legal_context(self):
        got = classes("Decreto 62-2023")
        self.assertIn((NumericClass.LEGAL_INSTRUMENT_ID, "62-2023", None), got)
        self.assertNotIn(NumericClass.CALENDAR_DATE, [x[0] for x in got])

    def test_bare_hyphen_id_abstains(self):
        got = classes("Referencia 62-2023")
        self.assertIn(NumericClass.UNRESOLVED_NUMERIC, [x[0] for x in got])
        self.assertNotIn(NumericClass.LEGAL_INSTRUMENT_ID, [x[0] for x in got])

    def test_explicit_hnl_exact_decimal(self):
        got = classes("Monto L. 1,250.00")
        self.assertIn((NumericClass.MONETARY_AMOUNT, "1250.00", "HNL"), got)

    def test_explicit_european_hnl_exact_decimal(self):
        got = classes("Monto 1.250,00 lempiras")
        self.assertIn((NumericClass.MONETARY_AMOUNT, "1250.00", "HNL"), got)

    def test_usd(self):
        got = classes("USD 10.50")
        self.assertIn((NumericClass.MONETARY_AMOUNT, "10.50", "USD"), got)

    def test_page_number(self):
        got = classes("Página 37")
        self.assertIn((NumericClass.PAGE_LIST_NUMBER, "37", None), got)
        self.assertNotIn(NumericClass.MONETARY_AMOUNT, [x[0] for x in got])

    def test_month_year(self):
        got = classes("noviembre 2024")
        self.assertIn((NumericClass.CALENDAR_DATE, "2024-11", None), got)

    def test_explicit_contract_amount_role_hint(self):
        candidates = classify_line(line("Monto del contrato L. 1,250.00"))
        money = next(c for c in candidates if c.semantic_class == NumericClass.MONETARY_AMOUNT)
        self.assertEqual("contract_amount", money.role_hint)

    def test_explicit_payment_date_role_hint(self):
        candidates = classify_line(line("Fecha de pago 10-11-2020"))
        day = next(c for c in candidates if c.semantic_class == NumericClass.CALENDAR_DATE)
        self.assertEqual("payment_date", day.role_hint)

    def test_spans_preserved(self):
        candidates = classify_line(line("Monto: L. 1,250.00"))
        money = next(c for c in candidates if c.semantic_class == NumericClass.MONETARY_AMOUNT)
        self.assertEqual("L. 1,250.00", money.surface_text)
        self.assertEqual("L. 1,250.00", "Monto: L. 1,250.00"[money.span_start:money.span_end])

if __name__ == "__main__":
    unittest.main()
