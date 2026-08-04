from __future__ import annotations

from fractions import Fraction
import tempfile
import unittest

from discovery_power import DiscoveryInventory, DiscoveryPlanner, DiscoverySource, Observation, chapman_population_estimate, compare_snapshots, completion_certificate, impossibility_certificate, verify_discovery_receipt
from benchmark import ARCHETYPES, DOMAINS, aggregate_fixture, check_domain, frequency_inventory, obs, planner_fixture, run_benchmark


class OpenWorldDiscoveryPowerTests(unittest.TestCase):
    def test_all_preregistered_scenarios_pass(self) -> None:
        rows = [row for domain in DOMAINS for row in check_domain(domain)]
        self.assertEqual(len(rows), 72)
        self.assertTrue(all(row["passed"] for row in rows))

    def test_each_domain_has_all_archetypes_once(self) -> None:
        for domain in DOMAINS:
            rows = check_domain(domain)
            self.assertEqual(tuple(row["archetype"] for row in rows), ARCHETYPES)
            self.assertEqual(len({row["archetype"] for row in rows}), 12)

    def test_invalid_and_duplicate_records_do_not_inflate_power(self) -> None:
        stats = frequency_inventory("research").stats()
        self.assertEqual((stats.observation_count, stats.valid_observation_count, stats.observed_unique, stats.duplicate_observations), (8, 7, 4, 3))

    def test_good_turing_and_chao_are_exact_fractions(self) -> None:
        stats = frequency_inventory("software").stats()
        self.assertEqual(stats.sample_coverage, Fraction(5, 7))
        self.assertEqual(stats.missing_mass, Fraction(2, 7))
        self.assertEqual(stats.chao_lower_bound, Fraction(9, 2))
        self.assertEqual(stats.chao_unseen_estimate, Fraction(1, 2))

    def test_capture_recapture_uses_overlap(self) -> None:
        self.assertEqual(chapman_population_estimate({"a", "b", "c", "d"}, {"c", "d", "e", "f"}), Fraction(22, 3))

    def test_source_selection_counts_unique_gain_not_raw_rows(self) -> None:
        planner, sources = planner_fixture("finance")
        value = planner.source_value(sources["finance:duplicate_source"], ["finance:known"])
        self.assertEqual((value.expected_valid_observations, value.expected_unique_gain, value.expected_duplicate_observations), (4, 1, 3))

    def test_probe_updates_posterior_and_next_source(self) -> None:
        planner, _ = planner_fixture("logistics")
        exhausted = ["logistics:probe", "logistics:duplicate_source", "logistics:positive_source"]
        before = planner.choose_next_source([], exhausted=exhausted)
        posterior = planner.posterior_after(source_name="logistics:probe", observed_canonical_ids=["logistics:signal_rich"])
        after = DiscoveryPlanner(worlds=planner.worlds, prior=posterior, sources=planner.sources).choose_next_source([], exhausted=exhausted)
        self.assertEqual(before.source, "logistics:a_lean_source")
        self.assertEqual(after.source, "logistics:z_rich_source")
        self.assertEqual(posterior["logistics:rich"], 1)

    def test_exact_and_estimated_stopping_are_not_conflated(self) -> None:
        exact = DiscoveryInventory([obs("physical", "s", "1", "a"), obs("physical", "s", "2", "b")])
        exact_cert = completion_certificate(inventory=exact, authoritative_total=2)
        estimated = DiscoveryInventory([obs("physical", "s", "1", "a"), obs("physical", "s", "2", "a")])
        estimated_cert = completion_certificate(inventory=estimated, remaining_source_values=[])
        self.assertEqual((exact_cert.status, exact_cert.exact), ("EXACT_COMPLETE", True))
        self.assertEqual((estimated_cert.status, estimated_cert.exact), ("ESTIMATED_SATURATED", False))

    def test_indistinguishable_worlds_emit_impossibility_certificate(self) -> None:
        source = DiscoverySource("governance:probe", 1, {"governance:complete": [Observation("s", "r", "same", "h")], "governance:incomplete": [Observation("s", "r", "same", "h")]})
        certificate = impossibility_certificate(complete_world="governance:complete", incomplete_world="governance:incomplete", sources=[source])
        self.assertIsNotNone(certificate)
        self.assertTrue(certificate.identical_observations)

    def test_snapshot_drift_is_partitioned(self) -> None:
        diff = compare_snapshots({"a": "h1", "b": "h2", "c": "h3"}, {"b": "h2x", "c": "h3", "d": "h4"})
        self.assertEqual((diff.added, diff.removed, diff.modified, diff.unchanged), (("d",), ("a",), ("b",), ("c",)))

    def test_iaip_aggregate_exposes_known_gap_and_estimation_blocker(self) -> None:
        diagnostic = aggregate_fixture("governance")
        self.assertEqual(diagnostic.known_missing_files, 40_283)
        self.assertEqual(diagnostic.status, "CONTINUE_KNOWN_GAP")
        self.assertEqual(set(diagnostic.missing_inputs_for_unseen_estimation), {"frequency_of_frequencies_f1_f2", "independent_source_capture_overlap"})
        self.assertEqual(diagnostic.physical_coverage, Fraction(2_530_927, 2_571_210))

    def test_receipt_is_deterministic_and_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = run_benchmark(first)["receipt"]
            b = run_benchmark(second)["receipt"]
            self.assertEqual(a, b)
            self.assertTrue(verify_discovery_receipt(a))
            tampered = dict(a)
            payload = dict(tampered["payload"])
            payload["passed"] = 71
            tampered["payload"] = payload
            self.assertFalse(verify_discovery_receipt(tampered))


if __name__ == "__main__":
    unittest.main()
