from __future__ import annotations

import unittest

from fin_abs_004_fdic import entity_split as base_split

from .protocol import (
    ENTITY_SPLIT_SEED,
    EXPECTED_BUCKET_RULE,
    FETCH_RANGES,
    TRAIN_BUCKET_END,
    VALIDATION_BUCKET_END,
    WINDOWS,
)


class UntouchedFdicProtocolTests(unittest.TestCase):
    def test_temporal_windows_leave_full_label_gaps(self) -> None:
        self.assertLess(WINDOWS["train"][1], WINDOWS["validation"][0])
        self.assertLess(WINDOWS["validation"][1], WINDOWS["test"][0])
        self.assertGreaterEqual(
            (WINDOWS["validation"][0] - WINDOWS["train"][1]).days,
            730,
        )
        self.assertGreaterEqual(
            (WINDOWS["test"][0] - WINDOWS["validation"][1]).days,
            730,
        )

    def test_fetch_ranges_supply_trailing_history(self) -> None:
        for (fetch_start, fetch_end), split in zip(
            FETCH_RANGES, ("train", "validation", "test"), strict=True
        ):
            self.assertLess(fetch_start, WINDOWS[split][0])
            self.assertEqual(fetch_end, WINDOWS[split][1])

    def test_bucket_contract_is_complete_and_disjoint(self) -> None:
        self.assertEqual(EXPECTED_BUCKET_RULE["train"], [0, 19])
        self.assertEqual(EXPECTED_BUCKET_RULE["validation"], [20, 29])
        self.assertEqual(EXPECTED_BUCKET_RULE["test"], [30, 99])
        covered = (
            set(range(0, TRAIN_BUCKET_END))
            | set(range(TRAIN_BUCKET_END, VALIDATION_BUCKET_END))
            | set(range(VALIDATION_BUCKET_END, 100))
        )
        self.assertEqual(covered, set(range(100)))

    def test_assignment_uses_new_seed_and_declared_boundaries(self) -> None:
        old = (
            base_split.ENTITY_SPLIT_SEED,
            base_split.TRAIN_BUCKET_END,
            base_split.VALIDATION_BUCKET_END,
        )
        try:
            base_split.ENTITY_SPLIT_SEED = ENTITY_SPLIT_SEED
            base_split.TRAIN_BUCKET_END = TRAIN_BUCKET_END
            base_split.VALIDATION_BUCKET_END = VALIDATION_BUCKET_END
            for cert in range(1, 500):
                bucket = base_split.entity_bucket(cert)
                expected = (
                    "train"
                    if bucket < 20
                    else "validation"
                    if bucket < 30
                    else "test"
                )
                self.assertEqual(base_split.assigned_split(expected, bucket), expected)
                for wrong in {"train", "validation", "test"} - {expected}:
                    self.assertIsNone(base_split.assigned_split(wrong, bucket))
        finally:
            (
                base_split.ENTITY_SPLIT_SEED,
                base_split.TRAIN_BUCKET_END,
                base_split.VALIDATION_BUCKET_END,
            ) = old


if __name__ == "__main__":
    unittest.main()
