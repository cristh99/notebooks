from __future__ import annotations

import unittest

from .benchmark import candidate_gate, counter_metrics, number_tokens, word_tokens


class BenchmarkTests(unittest.TestCase):
    def test_word_tokens_are_order_independent_inputs(self) -> None:
        left = word_tokens("Monto total L 98,765.43 contrato ABC-7")
        right = word_tokens("ABC-7 contrato 98,765.43 L total Monto")
        self.assertEqual(counter_metrics(left, right)["f1"], 1.0)

    def test_numeric_normalization_removes_thousands_separator(self) -> None:
        self.assertIn("98765.43", number_tokens("L 98,765.43"))
        self.assertIn("000-001-01-00000524", number_tokens("Factura 000-001-01-00000524"))

    def test_tenfold_error_gate(self) -> None:
        baseline = {
            "total_wall_seconds": 100.0,
            "word_micro": {"error": 0.20, "recall": 0.80},
            "numeric_micro": {"error": 0.10, "recall": 0.90},
            "empty_pages": 0,
            "catastrophic_pages": 1,
        }
        candidate = {
            "total_wall_seconds": 9.0,
            "word_micro": {"error": 0.02, "recall": 0.98},
            "numeric_micro": {"error": 0.01, "recall": 0.99},
            "empty_pages": 0,
            "catastrophic_pages": 0,
        }
        gate = candidate_gate(baseline, candidate)
        self.assertTrue(gate["full_10x_gate"])

    def test_speed_alone_never_passes(self) -> None:
        baseline = {
            "total_wall_seconds": 100.0,
            "word_micro": {"error": 0.20, "recall": 0.80},
            "numeric_micro": {"error": 0.10, "recall": 0.90},
            "empty_pages": 0,
            "catastrophic_pages": 0,
        }
        candidate = {
            "total_wall_seconds": 1.0,
            "word_micro": {"error": 0.19, "recall": 0.81},
            "numeric_micro": {"error": 0.09, "recall": 0.91},
            "empty_pages": 0,
            "catastrophic_pages": 0,
        }
        gate = candidate_gate(baseline, candidate)
        self.assertTrue(gate["speed_10x"])
        self.assertFalse(gate["full_10x_gate"])


if __name__ == "__main__":
    unittest.main()
