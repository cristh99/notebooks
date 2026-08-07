from __future__ import annotations

import copy
import unittest

from .adapter import adapt_statement, audit_upstream_schema
from .evaluate import metrics
from .verifier import POLICY_ID, predict, reporting_variant


def clean_statement() -> dict:
    return {
        "company": "Test Corp",
        "period": "FY2025",
        "currency": "USD",
        "unit": "as-filed",
        "income_statement": {
            "revenue": 1000.0,
            "cost_of_goods_sold": -600.0,
            "gross_profit": 400.0,
            "operating_expenses": -180.0,
            "depreciation_amortization": -20.0,
            "operating_income": 200.0,
            "interest_expense": -10.0,
            "income_before_tax": 190.0,
            "income_tax_expense": -40.0,
            "net_income": 150.0,
        },
        "balance_sheet": {
            "current_year": {
                "cash_and_equivalents": 250.0,
                "accounts_receivable": 100.0,
                "inventory": 150.0,
                "total_current_assets": 500.0,
                "property_plant_equipment": 500.0,
                "total_assets": 1000.0,
                "accounts_payable": 100.0,
                "short_term_debt": 100.0,
                "total_current_liabilities": 200.0,
                "long_term_debt": 300.0,
                "total_liabilities": 500.0,
                "retained_earnings": 370.0,
                "total_equity": 500.0,
                "total_liabilities_and_equity": 1000.0,
            },
            "prior_year": {
                "cash_and_equivalents": 200.0,
                "accounts_receivable": 90.0,
                "inventory": 110.0,
                "total_current_assets": 400.0,
                "property_plant_equipment": 500.0,
                "total_assets": 900.0,
                "accounts_payable": 80.0,
                "short_term_debt": 100.0,
                "total_current_liabilities": 180.0,
                "long_term_debt": 270.0,
                "total_liabilities": 450.0,
                "retained_earnings": 250.0,
                "total_equity": 450.0,
                "total_liabilities_and_equity": 900.0,
            },
        },
        "cash_flow_statement": {
            "net_income": 150.0,
            "depreciation_amortization": 20.0,
            "changes_in_working_capital": -20.0,
            "cash_from_operations": 150.0,
            "capital_expenditures": -70.0,
            "cash_from_investing": -70.0,
            "debt_repayment": 0.0,
            "dividends_paid": -30.0,
            "cash_from_financing": -30.0,
            "net_change_in_cash": 50.0,
            "beginning_cash": 200.0,
            "ending_cash": 250.0,
        },
    }


def processed_statement() -> dict:
    def item(values):
        return {"xbrl_concept": "x", "periods": {fy: {"value": value} for fy, value in values.items()}}

    return {
        "metadata": {
            "entity_name": "Adapter Corp",
            "fiscal_years": ["FY2024", "FY2025"],
        },
        "balance_sheet": {
            "line_items": {
                "Total Assets": item({"FY2024": 900.0, "FY2025": 1000.0}),
                "Total Liabilities": item({"FY2024": 450.0, "FY2025": 500.0}),
                "Total Stockholders Equity": item({"FY2024": 450.0, "FY2025": 500.0}),
                "Total Liabilities and Equity": item({"FY2024": 900.0, "FY2025": 1000.0}),
                "Cash and Cash Equivalents": item({"FY2024": 200.0, "FY2025": 250.0}),
                "Accounts Receivable": item({"FY2024": 90.0, "FY2025": 100.0}),
                "Inventory": item({"FY2024": 110.0, "FY2025": 150.0}),
                "Total Current Assets": item({"FY2024": 400.0, "FY2025": 500.0}),
                "Property, Plant and Equipment (net)": item({"FY2024": 500.0, "FY2025": 500.0}),
                "Total Current Liabilities": item({"FY2024": 180.0, "FY2025": 200.0}),
                "Retained Earnings (Accumulated Deficit)": item({"FY2024": 250.0, "FY2025": 370.0}),
            }
        },
        "income_statement": {
            "line_items": {
                "Total Revenue": item({"FY2025": 1000.0}),
                "Gross Profit": item({"FY2025": 400.0}),
                "Operating Income (Loss)": item({"FY2025": 200.0}),
                "Income Tax Expense": item({"FY2025": 40.0}),
                "Net Income (Loss)": item({"FY2025": 150.0}),
            }
        },
        "cash_flow_statement": {
            "line_items": {
                "Cash from Operating Activities": item({"FY2025": 150.0}),
                "Cash from Investing Activities": item({"FY2025": -70.0}),
                "Cash from Financing Activities": item({"FY2025": -30.0}),
                "Depreciation & Amortization": item({"FY2025": 20.0}),
                "Dividends Paid": item({"FY2025": 30.0}),
            }
        },
    }


class FinAbs001ATests(unittest.TestCase):
    def test_clean_statement_passes(self) -> None:
        result = predict(clean_statement())
        self.assertEqual(result["policy_id"], POLICY_ID)
        self.assertEqual(result["decision"], "CLEAN")
        self.assertEqual(result["failed_count"], 0)
        self.assertGreaterEqual(result["check_count"], 20)

    def test_arithmetic_error_is_detected(self) -> None:
        value = clean_statement()
        value["income_statement"]["revenue"] = 1100.0
        result = predict(value)
        self.assertEqual(result["decision"], "ERROR")
        self.assertIn("IS_GROSS_PROFIT", {row["check_id"] for row in result["failed_checks"]})

    def test_cross_statement_error_is_detected(self) -> None:
        value = clean_statement()
        value["cash_flow_statement"]["ending_cash"] = 300.0
        result = predict(value)
        self.assertEqual(result["decision"], "ERROR")
        ids = {row["check_id"] for row in result["failed_checks"]}
        self.assertIn("CROSS_ENDING_CASH", ids)

    def test_missing_statements_fail_closed(self) -> None:
        value = {"income_statement": clean_statement()["income_statement"]}
        result = predict(value)
        self.assertEqual(result["decision"], "ABSTAIN")

    def test_rounded_millions_remain_clean(self) -> None:
        value = clean_statement()
        for section in ("income_statement", "cash_flow_statement"):
            for key in value[section]:
                value[section][key] *= 1_000_000
        for period in ("current_year", "prior_year"):
            for key in value["balance_sheet"][period]:
                value["balance_sheet"][period][key] *= 1_000_000
        rounded = reporting_variant(value)
        self.assertEqual(predict(rounded)["decision"], "CLEAN")

    def test_adapter_produces_checkable_statement(self) -> None:
        result = adapt_statement(processed_statement(), "TEST", "TEST.json")
        self.assertEqual(result.status, "ADAPTED")
        self.assertEqual(result.fiscal_year, "FY2025")
        assert result.statement is not None
        self.assertEqual(predict(result.statement)["decision"], "CLEAN")

    def test_metrics_treat_abstention_as_missed_error(self) -> None:
        rows = [
            {"observable": True, "gold_error": False, "decision": "CLEAN", "localized": False, "categories": []},
            {"observable": True, "gold_error": True, "decision": "ABSTAIN", "localized": False, "categories": ["AE"]},
        ]
        result = metrics(rows)
        self.assertEqual(result["true_negative"], 1)
        self.assertEqual(result["false_negative"], 1)
        self.assertEqual(result["recall"], 0.0)
        self.assertEqual(result["coverage"], 0.5)

    def test_adapter_is_explicitly_not_raw_builder_schema(self) -> None:
        # The public upstream committed parsed file shape lacks the simplified
        # top-level company/revenue/current_year contract expected by its builder.
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "TEST.json"
            path.write_text(json.dumps(processed_statement()), encoding="utf-8")
            audit = audit_upstream_schema(Path(temp))
            self.assertEqual(audit["pipeline_status"], "SCHEMA_MISMATCH")
            self.assertEqual(audit["dataset_builder_compatible"], 0)


if __name__ == "__main__":
    unittest.main()
