from __future__ import annotations

import unittest

from data_science_dominance.fresh_gate_v1.benchmark import run_benchmark


class InternalBenchmarkTests(unittest.TestCase):
    def test_internal_benchmark_is_exact_and_conservative(self) -> None:
        receipt = run_benchmark(population=500)
        self.assertEqual(receipt.verdict, "PASS")
        self.assertEqual(receipt.clean_resolution.precision, 1.0)
        self.assertEqual(receipt.clean_resolution.recall, 1.0)
        self.assertEqual(receipt.clean_resolution.false_positive, 0)
        self.assertEqual(receipt.adversarial_quarantine_rate, 1.0)
        self.assertTrue(receipt.temporal_exact)
        self.assertEqual(
            receipt.temporal_projects_selected,
            receipt.temporal_projects_expected,
        )


if __name__ == "__main__":
    unittest.main()
