from __future__ import annotations

import unittest

from .evaluate_holdout import (
    aggregate,
    compare_algorithms,
    order_metrics,
    transitive_closure,
)


class RouterEvaluationTests(unittest.TestCase):
    def test_transitive_closure(self) -> None:
        self.assertEqual(
            transitive_closure(["A", "B", "C"], [["A", "B"], ["B", "C"]]),
            [("A", "B"), ("A", "C"), ("B", "C")],
        )

    def test_parallel_nodes_are_not_forced(self) -> None:
        annotation = {
            "semantic_block_ids": ["A", "B", "C"],
            "correct_order": ["A", "B", "C"],
            "must_precede": [["A", "B"], ["A", "C"]],
        }
        left = order_metrics(["A", "B", "C"], annotation)
        right = order_metrics(["A", "C", "B"], annotation)
        self.assertTrue(left["exact_partial_order"])
        self.assertTrue(right["exact_partial_order"])

    def test_router_better_than_universals(self) -> None:
        row = {
            "baseline": {"constraint_accuracy": 0.8, "canonical_read_order_edit": 0.2, "exact_partial_order": False},
            "geometry": {"constraint_accuracy": 0.9, "canonical_read_order_edit": 0.1, "exact_partial_order": False},
            "router": {"constraint_accuracy": 1.0, "canonical_read_order_edit": 0.0, "exact_partial_order": True},
        }
        comparison = compare_algorithms(row)
        self.assertEqual(comparison["winners"], ["router"])
        self.assertEqual(comparison["router_disposition"], "ROUTER_BETTER")

    def test_router_ties_best_universal(self) -> None:
        row = {
            "baseline": {"constraint_accuracy": 1.0, "canonical_read_order_edit": 0.0, "exact_partial_order": True},
            "geometry": {"constraint_accuracy": 0.8, "canonical_read_order_edit": 0.2, "exact_partial_order": False},
            "router": {"constraint_accuracy": 1.0, "canonical_read_order_edit": 0.0, "exact_partial_order": True},
        }
        comparison = compare_algorithms(row)
        self.assertEqual(comparison["router_disposition"], "ROUTER_TIES_BEST_UNIVERSAL")

    def test_aggregate_denominators(self) -> None:
        rows = [
            {
                "router": {
                    "semantic_blocks": 3,
                    "constraint_pairs": 3,
                    "correct_constraint_pairs": 3,
                    "constraint_accuracy": 1.0,
                    "exact_partial_order": True,
                    "canonical_read_order_edit": 0.0,
                }
            },
            {
                "router": {
                    "semantic_blocks": 2,
                    "constraint_pairs": 1,
                    "correct_constraint_pairs": 0,
                    "constraint_accuracy": 0.0,
                    "exact_partial_order": False,
                    "canonical_read_order_edit": 0.5,
                }
            },
        ]
        result = aggregate(rows, "router")
        self.assertEqual(result["constraint_pairs"], 4)
        self.assertEqual(result["weighted_constraint_accuracy"], 0.75)
        self.assertEqual(result["mean_canonical_read_order_edit"], 0.25)


if __name__ == "__main__":
    unittest.main()
