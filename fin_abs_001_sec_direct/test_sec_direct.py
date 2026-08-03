from __future__ import annotations

import copy
import unittest

from .benchmark import (
    build_instances,
    evaluate_instances,
    reporting_variant,
)
from .constants import ABSOLUTE_SCORE_BEFORE
from .metrics import metrics
from .policy import predict
from .report import build_report
from .sec_extract import extract_case


def fact(
    value,
    *,
    accn="0001-24-000001",
    end="2024-12-31",
    start=None,
    filed="2025-02-15",
):
    result = {
        "val": value,
        "accn": accn,
        "end": end,
        "filed": filed,
        "form": "10-K",
        "fy": 2024,
        "fp": "FY",
    }
    if start is not None:
        result["start"] = start
    return result


def companyfacts():
    accn = "0001-24-000001"
    end = "2024-12-31"
    start = "2024-01-01"
    prior = "2023-12-31"
    concepts = {
        "Assets": [
            fact(1000, accn=accn, end=end)
        ],
        "LiabilitiesAndStockholdersEquity": [
            fact(1000, accn=accn, end=end)
        ],
        "Liabilities": [
            fact(600, accn=accn, end=end)
        ],
        (
            "StockholdersEquityIncludingPortion"
            "AttributableToNoncontrollingInterest"
        ): [
            fact(400, accn=accn, end=end)
        ],
        "CashAndCashEquivalentsAtCarryingValue": [
            fact(150, accn=accn, end=end),
            fact(100, accn=accn, end=prior),
        ],
        (
            "RevenueFromContractWithCustomer"
            "ExcludingAssessedTax"
        ): [
            fact(
                800,
                accn=accn,
                end=end,
                start=start,
            )
        ],
        "CostOfRevenue": [
            fact(
                500,
                accn=accn,
                end=end,
                start=start,
            )
        ],
        "GrossProfit": [
            fact(
                300,
                accn=accn,
                end=end,
                start=start,
            )
        ],
        (
            "NetCashProvidedByUsedIn"
            "OperatingActivities"
        ): [
            fact(
                120,
                accn=accn,
                end=end,
                start=start,
            )
        ],
        (
            "NetCashProvidedByUsedIn"
            "InvestingActivities"
        ): [
            fact(
                -40,
                accn=accn,
                end=end,
                start=start,
            )
        ],
        (
            "NetCashProvidedByUsedIn"
            "FinancingActivities"
        ): [
            fact(
                -35,
                accn=accn,
                end=end,
                start=start,
            )
        ],
        "EffectOfExchangeRateOnCashAndCashEquivalents": [
            fact(
                5,
                accn=accn,
                end=end,
                start=start,
            )
        ],
        "CashAndCashEquivalentsPeriodIncreaseDecrease": [
            fact(
                50,
                accn=accn,
                end=end,
                start=start,
            )
        ],
    }
    return {
        "entityName": "Synthetic Public Company",
        "sic": 3571,
        "sicDescription": "Electronic Computers",
        "facts": {
            "us-gaap": {
                concept: {
                    "units": {"USD": values}
                }
                for concept, values
                in concepts.items()
            }
        },
    }


COMPANY = {
    "ticker": "SYN",
    "cik": "0000000001",
    "name": "Synthetic",
}


class SecDirectTests(unittest.TestCase):
    def test_extracts_direct_case(self):
        case = extract_case(
            companyfacts(),
            COMPANY,
        )
        self.assertIsNotNone(case)
        assert case is not None
        self.assertGreaterEqual(
            case["enabled_relation_count"],
            5,
        )
        self.assertEqual(
            set(case["values"]),
            set(case["provenance"]),
        )
        self.assertEqual(
            predict(case)["decision"],
            "CLEAN",
        )

    def test_injected_errors_are_detected(self):
        case = extract_case(
            companyfacts(),
            COMPANY,
        )
        assert case is not None
        rows = evaluate_instances(
            build_instances([case])
        )
        result = metrics(rows)
        self.assertEqual(
            result["false_positive_rate"],
            0.0,
        )
        self.assertEqual(
            result["precision"],
            1.0,
        )
        self.assertEqual(
            result["recall"],
            1.0,
        )

    def test_rounded_clean_case_remains_clean(self):
        case = extract_case(
            companyfacts(),
            COMPANY,
        )
        assert case is not None
        rounded = reporting_variant(
            case,
            divisor=10.0,
        )
        self.assertEqual(
            predict(rounded)["decision"],
            "CLEAN",
        )

    def test_unreconciled_relation_is_excluded(self):
        broken = companyfacts()
        broken["facts"]["us-gaap"][
            "GrossProfit"
        ]["units"]["USD"][0]["val"] = 275
        case = extract_case(
            broken,
            COMPANY,
        )
        self.assertIsNotNone(case)
        assert case is not None
        self.assertNotIn(
            "IS_GROSS_PROFIT",
            case["enabled_relation_ids"],
        )
        self.assertIn(
            "IS_GROSS_PROFIT",
            {
                item["relation_id"]
                for item
                in case[
                    "source_rejected_relations"
                ]
            },
        )

    def test_score_needs_every_gate(self):
        case = extract_case(
            companyfacts(),
            COMPANY,
        )
        assert case is not None
        instances = build_instances([case])
        exact = evaluate_instances(instances)
        rounded = evaluate_instances(
            instances,
            rounded=True,
        )
        report = build_report(
            [case],
            [{"ticker": "SYN", "status": "CACHE"}],
            exact,
            rounded,
            cases_file_sha256="synthetic",
        )
        self.assertEqual(
            report["payload"]["absolute_score"][
                "after"
            ],
            ABSOLUTE_SCORE_BEFORE,
        )
        self.assertEqual(
            report["payload"]["status"],
            "OPEN_SEC_DIRECT_BREADTH",
        )

    def test_tampered_case_fails(self):
        case = extract_case(
            companyfacts(),
            COMPANY,
        )
        assert case is not None
        altered = copy.deepcopy(case)
        altered["values"]["assets"] = 1200
        self.assertEqual(
            predict(altered)["decision"],
            "ERROR",
        )


if __name__ == "__main__":
    unittest.main()
