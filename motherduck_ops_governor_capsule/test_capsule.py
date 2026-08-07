from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import candidate  # noqa: E402
import oracle  # noqa: E402
import verify  # noqa: E402


class MotherDuckGovernorCapsuleTests(unittest.TestCase):
    def test_frozen_fixtures(self) -> None:
        result = verify.frozen_fixture_check()
        self.assertEqual(result["fixture_count"], 22)
        self.assertEqual(result["fixture_passed"], 22)
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["invalid_input_rejected"])

    def test_exhaustive_candidate_matches_independent_oracle(self) -> None:
        result = verify.exhaustive_check()
        self.assertEqual(result["cases"], 62208)
        self.assertEqual(result["candidate_oracle_mismatches"], 0)
        self.assertEqual(result["mismatch_examples"], [])

    def test_baselines_are_not_equivalent(self) -> None:
        result = verify.exhaustive_check()
        for name, stats in result["baselines"].items():
            with self.subTest(name=name):
                self.assertGreater(stats["mismatches"], 0)

        self.assertGreater(
            result["baselines"]["disable_all"]["lease_violation"], 0
        )
        self.assertGreater(
            result["baselines"]["perform_all"]["unsafe_accept"], 0
        )
        self.assertGreater(
            result["baselines"]["status_only"]["unsupported_action"], 0
        )
        self.assertGreater(
            result["baselines"]["ignore_leases"]["lease_violation"], 0
        )

    def test_candidate_packets_are_canonical(self) -> None:
        case = {
            "case_id": "canonical",
            "authorized": True,
            "reversible": True,
            "receipt_preserved": True,
            "scheduled": True,
            "identical_noop_count": 3,
        }
        packet = candidate.evaluate_case(case)
        reversed_case = dict(reversed(list(case.items())))
        replay = candidate.evaluate_case(reversed_case)
        self.assertEqual(packet, replay)
        self.assertEqual(
            json.dumps(packet, sort_keys=True, separators=(",", ":")),
            json.dumps(replay, sort_keys=True, separators=(",", ":")),
        )

    def test_oracle_and_candidate_reject_invalid_counts(self) -> None:
        case = {
            "case_id": "invalid",
            "authorized": True,
            "reversible": True,
            "receipt_preserved": True,
            "same_failure_count": -1,
        }
        with self.assertRaises(ValueError):
            candidate.evaluate_case(case)
        with self.assertRaises(ValueError):
            oracle.decide(case)


if __name__ == "__main__":
    unittest.main()
