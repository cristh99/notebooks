from __future__ import annotations

import json
import unittest

from fin_rvi_002_stage6.run_stage6 import (
    EXPECTED_UNION_SHA256,
    SEED,
    freeze_stage6,
)


class Stage6Tests(unittest.TestCase):
    @staticmethod
    def candidates() -> list[dict]:
        candidates = []
        for index in range(800):
            candidates.append(
                {
                    "candidate_id": f"candidate-{index:04d}",
                    "shared_code": f"CODE:SIT-CO-{index:03d}-2099",
                    "cardinality_type": "ONE_TO_ONE",
                    "relative_amount_difference": 0.1,
                    "absolute_days": 10,
                }
            )
        return candidates

    def test_real_exclusion_manifest_contract_is_hash_bound(self) -> None:
        self.assertEqual(
            EXPECTED_UNION_SHA256,
            "927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984",
        )

    def test_freeze_is_deterministic_on_real_shape(self) -> None:
        import fin_rvi_002_stage6.run_stage6 as module

        candidates = self.candidates()
        fake = {
            "schema": "fin-rvi-002/stage6-derived-exclusion-manifest/1",
            "shared_code_count": 0,
            "shared_codes_sha256": "0" * 64,
            "shared_codes": [],
        }
        original = module.derive_exclusion_manifest
        module.derive_exclusion_manifest = lambda _: fake
        try:
            first = freeze_stage6(json.loads(json.dumps(candidates)), 30)
            second = freeze_stage6(json.loads(json.dumps(candidates)), 30)
        finally:
            module.derive_exclusion_manifest = original
        self.assertEqual(
            [row["candidate_id"] for row in first],
            [row["candidate_id"] for row in second],
        )
        self.assertEqual(len(first), 30)
        self.assertTrue(
            all(row["stage6_selection_seed"] == SEED for row in first)
        )


if __name__ == "__main__":
    unittest.main()
