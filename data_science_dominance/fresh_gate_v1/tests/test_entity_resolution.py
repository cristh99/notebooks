from __future__ import annotations

import unittest

from data_science_dominance.fresh_gate_v1.entity_resolution import (
    Entity,
    ResolutionStatus,
    conservative_signature,
    digit_signature,
    is_superseded,
    ocr_signature,
    pair_score,
    resolve_entities,
)


class EntityResolutionTests(unittest.TestCase):
    def test_signatures_separate_precision_and_recall(self) -> None:
        left = "Award No. W91QF4-24-C-0001"
        right = "contract:w9iqf4_24_c_oooi"
        self.assertNotEqual(conservative_signature(left), conservative_signature(right))
        self.assertEqual(ocr_signature(left), ocr_signature(right))
        self.assertEqual(digit_signature(left), digit_signature(right))
        self.assertGreaterEqual(pair_score(left, right), 0.96)

    def test_cross_database_matches_are_one_to_one(self) -> None:
        left = [
            Entity("contract-1", "Award No. W91QF4-24-C-0001"),
            Entity("recipient-1", "UEI: ABC123"),
        ]
        right = [
            Entity("amount-1", "contract:w9iqf4_24_c_oooi"),
            Entity("recipient-master-1", "abc-123"),
            Entity("decoy", "W91QF4-24-C-0099"),
        ]
        batch = resolve_entities(left, right)
        self.assertEqual(
            batch.accepted_map(),
            {
                "contract-1": "amount-1",
                "recipient-1": "recipient-master-1",
            },
        )
        self.assertEqual(batch.audit.accepted, 2)
        self.assertEqual(batch.audit.ambiguous, 0)
        self.assertEqual(batch.audit.unmatched, 0)

    def test_ambiguous_ocr_collision_is_quarantined(self) -> None:
        left = [Entity("left", "AB-1200")]
        right = [
            Entity("right-a", "AB-120O"),
            Entity("right-b", "AB-I200"),
        ]
        batch = resolve_entities(left, right)
        resolution = batch.resolutions[0]
        self.assertEqual(resolution.status, ResolutionStatus.AMBIGUOUS)
        self.assertIsNone(resolution.right_key)
        self.assertAlmostEqual(resolution.margin, 0.0)

    def test_materially_different_identifier_does_not_merge(self) -> None:
        score = pair_score("AA-1001", "AA-1002")
        self.assertLess(score, 0.84)
        batch = resolve_entities(
            [Entity("left", "AA-1001")],
            [Entity("right", "AA-1002")],
        )
        self.assertEqual(batch.resolutions[0].status, ResolutionStatus.UNMATCHED)

    def test_superseded_rows_are_explicitly_excluded(self) -> None:
        self.assertTrue(is_superseded("Award: ABC-100_OLD"))
        batch = resolve_entities(
            [Entity("old", "Award: ABC-100_OLD"), Entity("live", "ABC-100")],
            [Entity("target", "contract:abc100")],
        )
        by_key = {resolution.left_key: resolution for resolution in batch.resolutions}
        self.assertEqual(by_key["old"].status, ResolutionStatus.SUPERSEDED)
        self.assertEqual(by_key["live"].right_key, "target")

    def test_mutual_best_prevents_many_to_one_silent_merge(self) -> None:
        left = [
            Entity("a", "UEI: XYZ100"),
            Entity("b", "Reference: XYZ1OO"),
        ]
        right = [Entity("master", "xyz-100")]
        batch = resolve_entities(left, right)
        accepted = [
            resolution
            for resolution in batch.resolutions
            if resolution.status in {ResolutionStatus.EXACT, ResolutionStatus.MATCHED}
        ]
        quarantined = [
            resolution
            for resolution in batch.resolutions
            if resolution.status == ResolutionStatus.AMBIGUOUS
        ]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(quarantined), 1)


if __name__ == "__main__":
    unittest.main()
