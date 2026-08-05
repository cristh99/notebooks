from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
engine = importlib.import_module("usaspending_v3_engine")


class NaicsDimensionTests(unittest.TestCase):
    def award(self, entity: str, naics: str, amount: float, recipient: str = ""):
        return engine.Award(entity_id=entity, award_id=entity, naics_code=naics, amount=amount, recipient_key=recipient, recipient_name=recipient)

    def test_distinct_two_digit_sectors_ignore_dimension_token_as_prefix(self):
        awards = [
            self.award("a", "236220", 11_000_000),
            self.award("b", "33-G411", 12_000_000),
            self.award("c", "naics-541512", 15_000_000),
            self.award("d", "611310", 9_000_000),
        ]
        plan = engine.plan_query("How many distinct 2-digit NAICS sectors are represented among contracts with an award amount of at least $10,000,000?", {}, [], [])
        self.assertEqual(engine.evaluate(plan, awards), 3)

    def test_argmax_sector_returns_code_and_breaks_tie_by_smaller_code(self):
        awards = [
            self.award("a1", "236220", 11_000_000),
            self.award("a2", "238210", 12_000_000),
            self.award("b1", "336411", 13_000_000),
            self.award("b2", "339999", 14_000_000),
        ]
        plan = engine.plan_query("Among contracts with an award amount of at least $10,000,000, which 2-digit NAICS sector has the most contracts? Return the 2-digit sector code, breaking ties by the smaller code.", {}, [], [])
        self.assertEqual(engine.evaluate(plan, awards), "23")

    def test_sector_metric_can_count_distinct_recipients(self):
        awards = [
            self.award("a1", "236220", 1, "Alpha Inc"),
            self.award("a2", "236220", 1, "Alpha Incorporated"),
            self.award("a3", "236220", 1, "Beta LLC"),
            self.award("b1", "336411", 1, "Gamma LLC"),
        ]
        plan = engine.plan_query("Which 2-digit NAICS sector has the most distinct recipients?", {}, [], [])
        self.assertEqual(engine.evaluate(plan, awards), "23")


class RecipientRegistryTests(unittest.TestCase):
    def setUp(self):
        engine._V3_RECIPIENTS = (
            engine.RecipientRecord("r1", "UEI:ABCD1234", engine.identifier_key("ABCD1234"), "Alpha Inc", "CA", 2, 10.0),
            engine.RecipientRecord("r2", "UEI:WXYZ9876", engine.identifier_key("WXYZ9876"), "ALPHA INCORPORATED", "CA", 1, 5.0),
            engine.RecipientRecord("r3", "UEI:ONE111", engine.identifier_key("ONE111"), "Beta LLC", "TX", 1, 4.0),
            engine.RecipientRecord("r4", "UEI:TWO222", engine.identifier_key("TWO222"), "Gamma Corp", "NY", 1, 3.0),
            engine.RecipientRecord("r5", "UEI:THREE333", engine.identifier_key("THREE333"), "Gamma Corporation", "NY", 1, 2.0),
        )

    def test_count_entities_with_more_than_one_uei(self):
        plan = engine.plan_query("How many distinct recipients in the recipients database are each associated with more than one UEI?", {}, [], [])
        self.assertEqual(engine.evaluate(plan, []), 2)

    def test_list_entities_with_multiple_uei(self):
        plan = engine.plan_query("List recipients with multiple UEIs", {}, [], [])
        self.assertEqual(len(engine.evaluate(plan, [])), 2)


class FallbackTests(unittest.TestCase):
    def test_unrelated_query_remains_v2_behavior(self):
        awards = [engine.Award(entity_id="a", award_id="a", amount=2_000_000)]
        plan = engine.plan_query("How many awards exceed $1,000,000?", {}, [], [])
        self.assertEqual(engine.evaluate(plan, awards), 1)

    def test_source_contains_no_fresh_query_numbers_or_ground_truth(self):
        source = Path(engine.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("query8", "query9", "query10", "ground_truth", "validate.py"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
