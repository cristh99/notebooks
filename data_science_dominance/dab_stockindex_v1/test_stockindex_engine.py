from __future__ import annotations

import inspect
import unittest

import stockindex_engine as engine


def row(symbol, day, open_, high, low, close, close_usd=None):
    meta = engine.metadata_for(symbol)
    return {
        "index": symbol,
        "date": engine.date.fromisoformat(day),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "adj_close": float(close),
        "close_usd": float(close if close_usd is None else close_usd),
        "exchange": meta.exchange,
        "country": meta.country,
        "region": meta.region,
        "currency": meta.currency,
    }


class PlannerTests(unittest.TestCase):
    def test_query1_semantics(self):
        plan = engine.plan_query("Which stock index in the Asia region has exhibited the highest average intraday volatility since 2020?")
        self.assertEqual(plan.metric, "intraday_volatility")
        self.assertEqual(plan.region, "Asia")
        self.assertEqual(plan.start_date, "2020-01-01")
        self.assertEqual(plan.direction, "max")

    def test_up_day_and_year_semantics(self):
        plan = engine.plan_query("Which European stock index had the most up days in 2022?")
        self.assertEqual(plan.metric, "up_days")
        self.assertEqual(plan.region, "Europe")
        self.assertEqual((plan.start_date, plan.end_date), ("2022-01-01", "2022-12-31"))

    def test_currency_and_low_direction(self):
        plan = engine.plan_query("Which stock index traded in yen had the lowest average USD closing price since 2021?")
        self.assertEqual(plan.currency, "JPY")
        self.assertEqual(plan.metric, "close_usd")
        self.assertEqual(plan.direction, "min")

    def test_scalar_difference(self):
        plan = engine.plan_query("How many more up days than down days did the Nikkei 225 have in 2023?")
        self.assertEqual(plan.metric, "up_minus_down")
        self.assertIn("^N225", plan.symbols)
        self.assertIsNone(plan.direction)

    def test_source_has_no_fresh_query_leakage(self):
        source = inspect.getsource(engine).lower()
        self.assertNotIn("query2", source)
        self.assertNotIn("query3", source)
        self.assertNotIn("ground_truth", source)
        self.assertNotIn("validate.py", source)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row("399001.SZ", "2021-01-01", 100, 140, 80, 120),
            row("399001.SZ", "2021-01-02", 100, 130, 90, 90),
            row("^N225", "2021-01-01", 100, 110, 95, 105),
            row("^N225", "2021-01-02", 100, 108, 98, 104),
            row("^GDAXI", "2022-01-01", 100, 104, 98, 103, 120),
            row("^GDAXI", "2022-01-02", 100, 105, 99, 102, 121),
            row("^FTSE", "2022-01-01", 100, 103, 97, 99, 110),
            row("^FTSE", "2022-01-02", 100, 106, 95, 98, 109),
        ]

    def test_asia_volatility_argmax(self):
        plan = engine.plan_query("Which stock index in Asia has the highest average intraday volatility since 2020?")
        self.assertEqual(engine.evaluate(plan, self.rows)[0], "399001.SZ")

    def test_up_days_argmax(self):
        plan = engine.plan_query("Which European stock index had the most up days in 2022?")
        self.assertEqual(engine.evaluate(plan, self.rows)[0], "^GDAXI")

    def test_lowest_close_usd(self):
        plan = engine.plan_query("Which European stock index had the lowest average closing price in USD in 2022?")
        self.assertEqual(engine.evaluate(plan, self.rows)[0], "^FTSE")

    def test_scalar_up_minus_down(self):
        plan = engine.plan_query("How many more up days than down days did the Nikkei 225 have in 2021?")
        self.assertEqual(engine.evaluate(plan, self.rows), 2.0)

    def test_currency_group(self):
        plan = engine.plan_query("Which currency had the highest average intraday volatility in Asia since 2020?")
        label, value = engine.evaluate(plan, self.rows)
        self.assertEqual(label, "CNY")
        self.assertGreater(value, 0)

    def test_top_k(self):
        plan = engine.plan_query("What are the top 2 European stock indices by average intraday volatility in 2022?")
        result = engine.evaluate(plan, self.rows)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "^FTSE")

    def test_cumulative_return(self):
        plan = engine.plan_query("What is the cumulative return of the Nikkei 225 in 2021?")
        value = engine.evaluate(plan, self.rows)
        self.assertAlmostEqual(value, 104 / 105 - 1.0)

    def test_render_primary_answer_first(self):
        text = engine.render_answer(("399001.SZ", 0.25))
        self.assertTrue(text.startswith("399001.SZ"))


if __name__ == "__main__":
    unittest.main()
