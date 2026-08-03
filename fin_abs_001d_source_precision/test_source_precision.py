from __future__ import annotations

import unittest

from fin_abs_001c_filedfact.run import Fact, Relation

from .run import (
    ABSOLUTE_SCORE_BEFORE,
    Precision,
    build_instances,
    build_report,
    enrich_relation,
    evaluate,
    metrics,
    precision_from_item,
)


def fact(fact_id: str, value: float, concept: str) -> Fact:
    return Fact(
        fact_id=fact_id,
        concept=concept,
        unit="monetary:USD",
        period="instant:2024-12-31",
        value=value,
        displayed_text=f"{value / 1000:,.0f}",
        text_start=0,
        text_end=1,
        dimensions=(),
        evidence_url="https://example.test/evidence",
    )


def relation(target_value: float = 1_000_000.0) -> Relation:
    target = fact("assets", target_value, "us-gaap#Assets")
    liabilities = fact("liabilities", 600_000.0, "us-gaap#Liabilities")
    equity = fact("equity", target_value - 600_000.0, "us-gaap#StockholdersEquity")
    return Relation(
        relation_id="a" * 64,
        family="STATEMENT_EQUATION",
        subtype="ASSETS_EQUALS_LIABILITIES_PLUS_EQUITY",
        target=target,
        terms=((liabilities, 1.0, False), (equity, 1.0, False)),
        passage={
            "chunk_id": "chunk",
            "cik": "1",
            "ticker": "SYN",
            "company_name": "Synthetic",
            "sic_code": "3571",
            "accession": "accn",
            "form_type": "10-K",
            "filed_at": "2025-01-01",
            "chunk_type": "table_context",
            "source_url": "https://www.sec.gov/test",
            "text_sha256": "b" * 64,
        },
    )


def precision(value: float, fact_id: str) -> Precision:
    return Precision(
        fact_id=fact_id,
        scale=3,
        decimals="-3",
        format="ixt:num-dot-decimal",
        display_decimals=0,
        quantum=1000.0,
        displayed_text=f"{value / 1000:,.0f}",
        source_value=value,
        display_consistent=True,
    )


class SourcePrecisionTests(unittest.TestCase):
    def test_source_quantum_comes_from_scale_and_display_decimals(self):
        value = precision_from_item(
            {
                "fact_id": "cash",
                "value": "51600000",
                "displayed_text": "51.6",
                "scale": 6,
                "decimals": "-5",
                "format": "ixt:num-dot-decimal",
            }
        )
        self.assertIsNotNone(value)
        assert value is not None
        self.assertEqual(value.quantum, 100000.0)
        self.assertTrue(value.display_consistent)

    def test_five_percent_error_is_frozen_only_when_resolvable(self):
        candidate = relation()
        index = {
            "assets": precision(1_000_000.0, "assets"),
            "liabilities": precision(600_000.0, "liabilities"),
            "equity": precision(400_000.0, "equity"),
        }
        enriched, status = enrich_relation(candidate, index)
        self.assertEqual(status["status"], "ELIGIBLE")
        self.assertIsNotNone(enriched)
        assert enriched is not None
        self.assertGreater(
            enriched["source_precision"]["actual_delta"],
            enriched["source_precision"]["resolvability_threshold"],
        )

    def test_source_precision_detects_frozen_error_without_false_positive(self):
        candidate = relation()
        index = {
            "assets": precision(1_000_000.0, "assets"),
            "liabilities": precision(600_000.0, "liabilities"),
            "equity": precision(400_000.0, "equity"),
        }
        enriched, _ = enrich_relation(candidate, index)
        assert enriched is not None
        instances = build_instances([enriched])
        rows = [evaluate(instance, "source_precision") for instance in instances]
        result = metrics(rows)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["false_positive_rate"], 0.0)

    def test_small_cohort_cannot_promote_absolute_score(self):
        candidate = relation()
        index = {
            "assets": precision(1_000_000.0, "assets"),
            "liabilities": precision(600_000.0, "liabilities"),
            "equity": precision(400_000.0, "equity"),
        }
        enriched, _ = enrich_relation(candidate, index)
        assert enriched is not None
        instances = build_instances([enriched])
        exact = [evaluate(instance, "exact") for instance in instances]
        source_rows = [evaluate(instance, "source_precision") for instance in instances]
        naive = [evaluate(instance, "naive_million") for instance in instances]
        report = build_report(
            {
                "revision": "8f7cb7e70be8b4dc6702c24927b355c1a287e4c0",
                "parquet_sha256": "c04bb39a676be9fbc5dd8a0addf99c2a92d9fcb2281657ba4c2bc5d6bf0b7a77",
                "selection_manifest_present_in_readme": True,
            },
            [candidate],
            [enriched],
            [{"relation_id": candidate.relation_id, "status": "ELIGIBLE"}],
            instances,
            exact,
            source_rows,
            naive,
            "relations",
            "instances",
        )
        self.assertEqual(
            report["payload"]["absolute_score"]["after"],
            ABSOLUTE_SCORE_BEFORE,
        )
        self.assertEqual(
            report["payload"]["status"],
            "OPEN_SOURCE_PRECISION_ROBUSTNESS",
        )


if __name__ == "__main__":
    unittest.main()
