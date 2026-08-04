import copy
import unittest

from lp_kal_benchmark import (
    ARCHETYPES,
    DOMAINS,
    TARGET_ARCHETYPE,
    build_scenarios,
    run_benchmark,
    scenario_manifest,
    sha256_json,
    verify_manifest,
)


class BenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = run_benchmark()
        self.summary = self.run["summary"]

    def test_balanced_cross_domain_manifest(self) -> None:
        self.assertEqual(len(build_scenarios()), len(DOMAINS) * len(ARCHETYPES))
        self.assertEqual(self.summary["scenario_count"], 96)

    def test_full_policy_passes_without_violations(self) -> None:
        self.assertTrue(self.summary["full_policy_pass"])
        full = next(e for e in self.summary["evaluations"] if e["policy"] == "lp_kal_full")
        self.assertEqual(full["exact_match_rate"], 1.0)
        self.assertEqual(full["positive_completion_rate"], 1.0)
        self.assertEqual(full["total_violations"], 0)

    def test_runtime_guarded_negative_control_ties(self) -> None:
        self.assertTrue(self.summary["monolithic_behavioral_equivalence"])
        self.assertTrue(self.summary["negative_control_equivalence"])

    def test_each_targeted_mutant_is_killed_in_every_domain(self) -> None:
        self.assertEqual(len(self.summary["targeted_mutants"]), len(TARGET_ARCHETYPE))
        for mutant, result in self.summary["targeted_mutants"].items():
            with self.subTest(mutant=mutant):
                self.assertTrue(result["killed_all_domains"])
                self.assertEqual(result["killed_domain_count"], len(DOMAINS))

    def test_mutation_score_is_complete(self) -> None:
        self.assertEqual(self.summary["mutation_score"], 1.0)

    def test_manifest_hash_is_order_independent(self) -> None:
        scenarios = list(build_scenarios())
        forward = scenario_manifest(scenarios)
        reverse = scenario_manifest(reversed(scenarios))
        self.assertEqual(sha256_json(forward), sha256_json(reverse))

    def test_manifest_tampering_is_rejected(self) -> None:
        manifest = self.run["manifest"]
        digest = sha256_json(manifest)
        tampered = copy.deepcopy(manifest)
        tampered["scenarios"][0]["expected"]["executed"] = not tampered["scenarios"][0]["expected"]["executed"]
        self.assertTrue(verify_manifest(manifest, digest))
        self.assertFalse(verify_manifest(tampered, digest))

    def test_summary_hash_is_deterministic(self) -> None:
        first = run_benchmark()["summary"]["summary_sha256"]
        second = run_benchmark()["summary"]["summary_sha256"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
