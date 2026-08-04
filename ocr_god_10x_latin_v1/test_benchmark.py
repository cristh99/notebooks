from __future__ import annotations

import unittest

from .benchmark import gate, normalize_output


class LatinBenchmarkTests(unittest.TestCase):
    def test_output_normalization_preserves_lines(self) -> None:
        self.assertEqual(normalize_output("  Uno  dos\n\n tres "), "Uno dos\ntres")

    def test_speed_without_quality_never_passes(self) -> None:
        baseline = {
            "total_wall_seconds": 100.0,
            "full_word": {"error": 0.1, "recall": 0.9},
            "full_numeric": {"error": 0.2, "recall": 0.8},
            "empty_pages": 0,
            "catastrophic_pages": 0,
        }
        candidate = {
            "total_wall_seconds": 5.0,
            "full_word": {"error": 0.09, "recall": 0.91},
            "full_numeric": {"error": 0.19, "recall": 0.81},
            "empty_pages": 0,
            "catastrophic_pages": 0,
        }
        result = gate(baseline, candidate)
        self.assertTrue(result["speed_10x"])
        self.assertFalse(result["full_10x_gate"])

    def test_full_tenfold_gate(self) -> None:
        baseline = {
            "total_wall_seconds": 100.0,
            "full_word": {"error": 0.1, "recall": 0.9},
            "full_numeric": {"error": 0.2, "recall": 0.8},
            "empty_pages": 0,
            "catastrophic_pages": 1,
        }
        candidate = {
            "total_wall_seconds": 9.0,
            "full_word": {"error": 0.01, "recall": 0.99},
            "full_numeric": {"error": 0.02, "recall": 0.98},
            "empty_pages": 0,
            "catastrophic_pages": 0,
        }
        self.assertTrue(gate(baseline, candidate)["full_10x_gate"])


if __name__ == "__main__":
    unittest.main()
