from __future__ import annotations

import unittest

from .evaluate_holdout import compare_page, order_metrics, transitive_closure


class HonduranEvaluationTests(unittest.TestCase):
    def test_transitive_closure(self) -> None:
        closure = transitive_closure(["A", "B", "C"], [["A", "B"], ["B", "C"]])
        self.assertEqual(closure, [("A", "B"), ("A", "C"), ("B", "C")])

    def test_cycle_rejected(self) -> None:
        with self.assertRaises(ValueError):
            transitive_closure(["A", "B"], [["A", "B"], ["B", "A"]])

    def test_parallel_column_is_not_forced(self) -> None:
        annotation = {
            "semantic_block_ids": ["A", "B", "C"],
            "correct_order": ["A", "B", "C"],
            "must_precede": [["A", "B"], ["A", "C"]],
        }
        left_first = order_metrics(["A", "B", "C"], annotation)
        right_first = order_metrics(["A", "C", "B"], annotation)
        self.assertTrue(left_first["exact_partial_order"])
        self.assertTrue(right_first["exact_partial_order"])
        self.assertEqual(left_first["constraint_accuracy"], 1.0)
        self.assertEqual(right_first["constraint_accuracy"], 1.0)

    def test_constraint_violation(self) -> None:
        annotation = {
            "semantic_block_ids": ["A", "B", "C"],
            "correct_order": ["A", "B", "C"],
            "must_precede": [["A", "B"], ["B", "C"]],
        }
        metrics = order_metrics(["B", "A", "C"], annotation)
        self.assertFalse(metrics["exact_partial_order"])
        self.assertIn(["A", "B"], metrics["violations"])

    def test_page_comparison_uses_constraints_first(self) -> None:
        row = {
            "baseline": {"constraint_accuracy": 1.0, "canonical_read_order_edit": 0.2},
            "geometry": {"constraint_accuracy": 0.9, "canonical_read_order_edit": 0.0},
        }
        self.assertEqual(compare_page(row), "BASELINE_BETTER")


if __name__ == "__main__":
    unittest.main()
