from __future__ import annotations

import unittest

from .audit import split_for_grcode


class ClrdAuditTests(unittest.TestCase):
    def test_split_is_deterministic(self) -> None:
        self.assertEqual(split_for_grcode("12345"), split_for_grcode("12345"))
        self.assertIn(split_for_grcode("12345"), {"train", "validation", "test"})

    def test_split_keeps_entity_together(self) -> None:
        values = {split_for_grcode("777") for _ in range(100)}
        self.assertEqual(len(values), 1)

    def test_split_has_all_buckets_on_large_synthetic_universe(self) -> None:
        values = {split_for_grcode(str(value)) for value in range(1000)}
        self.assertEqual(values, {"train", "validation", "test"})


if __name__ == "__main__":
    unittest.main()
