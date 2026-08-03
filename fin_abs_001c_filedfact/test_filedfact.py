from __future__ import annotations

import copy
import unittest

from .run import (
    ABSOLUTE_SCORE_BEFORE,
    build_instances,
    build_report,
    evaluate_instance,
    metrics,
    mine_relations,
    parse_facts,
)


def sample_row():
    displayed = ["1000", "1000", "600", "400", "800", "500", "300", "10", "20", "30"]
    text_parts = []
    spans = []
    cursor = 0
    for index, value in enumerate(displayed):
        token = f"v{index}={value}"
        if text_parts:
            cursor += 1
        start = cursor + len(f"v{index}=")
        end = start + len(value)
        text_parts.append(token)
        spans.append((start, end))
        cursor += len(token)
    text = " ".join(text_parts)

    def fact(index, concept, period, value, dimensions=None):
        start, end = spans[index]
        return {
            "fact_id": f"f{index}",
            "concept": concept,
            "unit": "monetary:USD",
            "period": period,
            "value": str(value),
            "displayed_text": displayed[index],
            "text_start": start,
            "text_end": end,
            "dimensions": dimensions or [],
            "evidence_url": f"https://example.test/f{index}",
        }

    instant = "instant:2024-12-31"
    duration = "duration:2024-01-01..2024-12-31"
    facts = [
        fact(0, "us-gaap#Assets", instant, 1000),
        fact(1, "us-gaap#LiabilitiesAndStockholdersEquity", instant, 1000),
        fact(2, "us-gaap#Liabilities", instant, 600),
        fact(3, "us-gaap#StockholdersEquity", instant, 400),
        fact(4, "us-gaap#RevenueFromContractWithCustomerExcludingAssessedTax", duration, 800),
        fact(5, "us-gaap#CostOfRevenue", duration, 500),
        fact(6, "us-gaap#GrossProfit", duration, 300),
        fact(
            7,
            "us-gaap#Goodwill",
            instant,
            10,
            [{"axis": "StatementBusinessSegmentsAxis", "member": "A"}],
        ),
        fact(
            8,
            "us-gaap#Goodwill",
            instant,
            20,
            [{"axis": "StatementBusinessSegmentsAxis", "member": "B"}],
        ),
        fact(9, "us-gaap#Goodwill", instant, 30),
    ]
    return {
        "chunk_id": "chunk-1",
        "cik": "0000000001",
        "ticker": "SYN",
        "company_name": "Synthetic",
        "sic_code": "3571",
        "accession": "000000000124000001",
        "form_type": "10-K",
        "filed_at": "2025-02-01",
        "chunk_type": "table_context",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1/test.htm",
        "text": text,
        "facts": facts,
    }


class FiledFactTests(unittest.TestCase):
    def test_span_grounding_is_required(self):
        row = sample_row()
        self.assertEqual(len(parse_facts(row)), 10)
        broken = copy.deepcopy(row)
        broken["facts"][0]["displayed_text"] = "999"
        self.assertEqual(len(parse_facts(broken)), 9)

    def test_mines_statement_and_dimension_relations(self):
        relations = mine_relations([sample_row()])
        families = {relation.family for relation in relations}
        subtypes = {relation.subtype for relation in relations}
        self.assertEqual(families, {"STATEMENT_EQUATION", "DIMENSION_TOTAL"})
        self.assertIn("ASSETS_EQUALS_LIABILITIES_AND_EQUITY_TOTAL", subtypes)
        self.assertIn("ASSETS_EQUALS_LIABILITIES_PLUS_EQUITY", subtypes)
        self.assertIn("GROSS_PROFIT_EQUALS_REVENUE_MINUS_COST", subtypes)
        self.assertIn("DIMENSION_MEMBER_SUM_EQUALS_TOTAL", subtypes)

    def test_controlled_errors_are_detected(self):
        relations = mine_relations([sample_row()])
        instances = build_instances(relations)
        exact = [evaluate_instance(instance, False) for instance in instances]
        result = metrics(exact)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["false_positive_rate"], 0.0)

    def test_small_cohort_cannot_change_score(self):
        row = sample_row()
        relations = mine_relations([row])
        instances = build_instances(relations)
        exact = [evaluate_instance(instance, False) for instance in instances]
        rounded = [evaluate_instance(instance, True) for instance in instances]
        source = {
            "revision": "a" * 40,
            "selection_manifest_present_in_readme": True,
            "row_count": 1,
        }
        report = build_report(
            source,
            [row],
            relations,
            instances,
            exact,
            rounded,
            "cases",
            "instances",
        )
        self.assertEqual(report["payload"]["absolute_score"]["after"], ABSOLUTE_SCORE_BEFORE)
        self.assertEqual(report["payload"]["status"], "OPEN_FILEDFACT_PASSAGE_BREADTH")


if __name__ == "__main__":
    unittest.main()
