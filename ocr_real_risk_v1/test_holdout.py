from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from ocr_real_risk_v1.core import (
    BOUND_ALPHA, Candidate, clopper_pearson_lower, clopper_pearson_upper,
    mutate_one_digit, parse_candidate_sources, round_robin,
)
from ocr_real_risk_v1.run_holdout import parse_partitions


class HoldoutTests(unittest.TestCase):
    def test_exact_bounds_use_bonferroni_split(self) -> None:
        observed = clopper_pearson_upper(0, 207)
        expected = 1.0 - BOUND_ALPHA ** (1.0 / 207.0)
        self.assertAlmostEqual(observed, expected, places=10)
        self.assertGreater(clopper_pearson_lower(20, 100), 0.09)

    def test_mutation_changes_exactly_one_digit(self) -> None:
        original = "109071"
        changed = mutate_one_digit(original, "sealed")
        self.assertEqual(len(original), len(changed))
        self.assertEqual(sum(a != b for a, b in zip(original, changed)), 1)

    def test_parse_raw_ocds_excludes_development_and_deduplicates(self) -> None:
        kept = {
            "ocid": "ocds-x-new-process",
            "buyer": {"id": "buyer-555", "name": "Buyer 555"},
            "tender": {
                "id": "NEW-001",
                "documents": [
                    {"documentType": "tenderNotice", "url": "http://x/Docs/Lic555NEW100-AvisodePrensa.pdf"},
                    {"documentType": "tenderNotice", "url": "http://x/Docs/Lic555NEW100-AvisodePrensa.pdf"},
                ],
            },
        }
        excluded = {
            "ocid": "ocds-x-CDE-SIT-063-2024",
            "buyer": {"id": "buyer-1211"},
            "tender": {
                "id": "CDE-SIT-063-2024",
                "documents": [{"documentType": "tenderNotice", "url": "http://x/Docs/Lic1211OLD100-AvisodePrensa.pdf"}],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oncae_2025.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps(kept) + "\n" + json.dumps(excluded) + "\n")
            candidates, census = parse_candidate_sources([path])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].institution_code, "BUYER555")
        self.assertEqual(census["excluded_development_releases"], 1)

    def test_round_robin_interleaves_institutions(self) -> None:
        values = [
            Candidate(f"http://x/{i}.pdf", "tenderNotice", "p", "o", code, code, 2025, i)
            for i, code in enumerate(["1", "1", "1", "2", "2", "3"])
        ]
        order = round_robin(values)
        self.assertEqual({item.institution_code for item in order[:3]}, {"1", "2", "3"})

    def test_partition_parser(self) -> None:
        self.assertEqual(parse_partitions("0-2,7"), frozenset({0, 1, 2, 7}))
        with self.assertRaises(ValueError):
            parse_partitions("100")


if __name__ == "__main__":
    unittest.main()
