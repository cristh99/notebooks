from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from skill_power_canary.capsule import build_report, load_scenarios, semantic_sha256


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "skill_power_canary" / "frozen_scenarios.json"
EXPECTED = ROOT / "skill_power_canary" / "expected_report.json"


class PublicCanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenarios = load_scenarios(SCENARIOS)
        cls.expected = json.loads(EXPECTED.read_text(encoding="utf-8"))

    def test_frozen_report_rebuilds_byte_for_byte(self) -> None:
        rebuilt = build_report(self.scenarios)
        self.assertEqual(rebuilt, self.expected)

    def test_governed_procedures_beat_frozen_baselines(self) -> None:
        metrics = self.expected["metrics"]
        self.assertEqual(metrics["governed_accuracy"], "32/32")
        self.assertEqual(metrics["baseline_accuracy"], "8/32")
        self.assertEqual(metrics["governed_false_activations"], 0)
        self.assertEqual(metrics["governed_unsafe_accepts"], 0)
        self.assertGreater(metrics["baseline_false_activations"], 0)
        self.assertGreater(metrics["baseline_unsafe_accepts"], 0)

    def test_each_skill_has_development_and_canary_cases(self) -> None:
        by_skill = self.expected["metrics"]["by_skill"]
        self.assertEqual(len(by_skill), 4)
        for metrics in by_skill.values():
            self.assertEqual(metrics["scenario_count"], 8)
            self.assertEqual(metrics["development_count"], 4)
            self.assertEqual(metrics["canary_count"], 4)
            self.assertEqual(metrics["governed_correct"], 8)
            self.assertLess(metrics["baseline_correct"], 8)

    def test_tampering_with_expected_terminal_fails_closed(self) -> None:
        tampered = copy.deepcopy(self.scenarios)
        tampered[0]["expected"] = "REJECTED"
        report = build_report(tampered)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertFalse(report["gates"]["governed_all_correct"])

    def test_semantic_digest_is_order_invariant(self) -> None:
        left = {"a": 1, "b": {"x": 2, "y": 3}}
        right = {"b": {"y": 3, "x": 2}, "a": 1}
        self.assertEqual(semantic_sha256(left), semantic_sha256(right))

    def test_scenario_ids_are_unique_and_frozen(self) -> None:
        identifiers = [scenario["id"] for scenario in self.scenarios]
        self.assertEqual(len(identifiers), 32)
        self.assertEqual(len(set(identifiers)), 32)
        self.assertEqual(
            semantic_sha256(self.scenarios),
            "a236c0da010345e3a1669345c6c708b67c16c26c1242e384b6984a792f1e93bd",
        )


if __name__ == "__main__":
    unittest.main()
