from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from god_pipeline.ensemble_extract import candidate_score, deterministic_tar_gz


class EnsembleTests(unittest.TestCase):
    def test_candidate_score_rewards_confidence_recall_and_words(self):
        weak = candidate_score({"mean_confidence": 60, "native_token_recall": 0.5}, 50)
        strong = candidate_score({"mean_confidence": 80, "native_token_recall": 0.8}, 100)
        self.assertGreater(strong, weak)

    def test_candidate_score_matches_frozen_formula(self):
        metrics = {"mean_confidence": 92.1039, "native_token_recall": 1.0}
        expected = 92.1039 + 20.0 + 167 / 168
        self.assertAlmostEqual(candidate_score(metrics, 167), expected, places=12)
        self.assertEqual(candidate_score({}, -5), 0.0)
        self.assertLess(candidate_score({}, 10**9), 1.0)

    def test_deterministic_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "b.txt").write_text("b", encoding="utf-8")
            (source / "a.txt").write_text("a", encoding="utf-8")
            first = deterministic_tar_gz(source, root / "first.tar.gz")
            second = deterministic_tar_gz(source, root / "second.tar.gz")
            self.assertEqual(first, second)
            self.assertEqual((root / "first.tar.gz").read_bytes(), (root / "second.tar.gz").read_bytes())


if __name__ == "__main__":
    unittest.main()
