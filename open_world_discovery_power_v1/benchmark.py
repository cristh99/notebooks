"""Preregistered benchmark for Open-World Discovery Power v1."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any
import csv
import hashlib
import json

from discovery_power import DiscoveryInventory, DiscoveryPlanner, DiscoverySource, Observation, aggregate_diagnostic, canonical_json, chapman_population_estimate, compare_snapshots, completion_certificate, digest, discovery_receipt, impossibility_certificate

DOMAINS = ("research", "software", "finance", "logistics", "physical", "governance")
ARCHETYPES = ("canonical_deduplication", "invalid_observation_gate", "sample_coverage_missing_mass", "chao_lower_bound", "capture_recapture_estimate", "overlap_adjusted_marginal", "adaptive_source_selection", "denominator_blindness", "honest_stopping", "impossibility_certificate", "snapshot_drift", "aggregate_real_diagnostic")


def q(domain: str, name: str) -> str:
    return f"{domain}:{name}"


def obs(domain: str, source: str, record: str, canonical: str, *, content: str | None = None, valid: bool = True) -> Observation:
    return Observation(q(domain, source), q(domain, record), q(domain, canonical), q(domain, content or canonical), valid)


def frequency_inventory(domain: str) -> DiscoveryInventory:
    return DiscoveryInventory([obs(domain, "s1", "r1", "a"), obs(domain, "s1", "r2", "b"), obs(domain, "s1", "r3", "c"), obs(domain, "s2", "r4", "c"), obs(domain, "s1", "r5", "d"), obs(domain, "s2", "r6", "d"), obs(domain, "s3", "r7", "d"), obs(domain, "s3", "bad", "invalid", valid=False)])


def planner_fixture(domain: str) -> tuple[DiscoveryPlanner, dict[str, DiscoverySource]]:
    lean, rich = q(domain, "lean"), q(domain, "rich")
    probe = DiscoverySource(q(domain, "probe"), 1, {lean: [obs(domain, "probe", "lean_signal", "signal_lean")], rich: [obs(domain, "probe", "rich_signal", "signal_rich")]})
    lean_source = DiscoverySource(q(domain, "a_lean_source"), 1, {lean: [obs(domain, "lean", "l1", "l1")], rich: []})
    rich_source = DiscoverySource(q(domain, "z_rich_source"), 2, {lean: [], rich: [obs(domain, "rich", "r1", "r1"), obs(domain, "rich", "r2", "r2")]})
    duplicate_source = DiscoverySource(q(domain, "duplicate_source"), 1, {lean: [obs(domain, "dup", "d1", "known"), obs(domain, "dup", "d2", "known"), obs(domain, "dup", "d3", "known"), obs(domain, "dup", "d4", "new_one")], rich: [obs(domain, "dup", "d1", "known"), obs(domain, "dup", "d2", "known"), obs(domain, "dup", "d3", "known"), obs(domain, "dup", "d4", "new_one")]})
    positive_source = DiscoverySource(q(domain, "positive_source"), 1, {lean: [obs(domain, "positive", "p1", "unseen")], rich: [obs(domain, "positive", "p1", "unseen")]})
    blocked_source = DiscoverySource(q(domain, "blocked_source"), 1, {lean: [], rich: []}, allowed=False, blocked_reason="permission_required")
    sources = {s.name: s for s in (probe, lean_source, rich_source, duplicate_source, positive_source, blocked_source)}
    return DiscoveryPlanner(worlds=[lean, rich], prior={lean: Fraction(1, 2), rich: Fraction(1, 2)}, sources=sources.values()), sources


def aggregate_fixture(domain: str):
    if domain == "governance":
        return aggregate_diagnostic(declared_records=2_574_240, declared_document_urls=2_571_210, physical_files=2_530_927, non_document_links=3_030)
    offset = DOMAINS.index(domain)
    records = 1_000 + offset * 100
    urls = records - 10
    files = urls - (5 + offset)
    return aggregate_diagnostic(declared_records=records, declared_document_urls=urls, physical_files=files, non_document_links=10)


def check_domain(domain: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    def add(archetype: str, passed: bool, observed: object, expected: object) -> None:
        rows.append({"domain": domain, "archetype": archetype, "passed": bool(passed), "observed": observed, "expected": expected})

    inventory = frequency_inventory(domain)
    stats = inventory.stats()
    add("canonical_deduplication", stats.valid_observation_count == 7 and stats.observed_unique == 4 and stats.duplicate_observations == 3, stats.to_dict(), {"valid": 7, "unique": 4, "duplicates": 3})
    add("invalid_observation_gate", stats.invalid_observation_count == 1 and q(domain, "invalid") not in inventory.canonical_items(), {"invalid_count": stats.invalid_observation_count, "items": sorted(inventory.canonical_items())}, "invalid observations contribute zero discovery")
    add("sample_coverage_missing_mass", stats.sample_coverage == Fraction(5, 7) and stats.missing_mass == Fraction(2, 7), {"coverage": str(stats.sample_coverage), "missing_mass": str(stats.missing_mass)}, {"coverage": "5/7", "missing_mass": "2/7"})
    add("chao_lower_bound", stats.chao_lower_bound == Fraction(9, 2) and stats.chao_unseen_estimate == Fraction(1, 2), {"lower_bound": str(stats.chao_lower_bound), "unseen": str(stats.chao_unseen_estimate)}, {"lower_bound": "9/2", "unseen": "1/2"})
    list_a = {q(domain, x) for x in ("a", "b", "c", "d")}
    list_b = {q(domain, x) for x in ("c", "d", "e", "f")}
    chapman = chapman_population_estimate(list_a, list_b)
    add("capture_recapture_estimate", chapman == Fraction(22, 3) and chapman - len(list_a | list_b) == Fraction(4, 3), {"estimate": str(chapman), "observed_union": len(list_a | list_b), "estimated_unseen": str(chapman - len(list_a | list_b))}, {"estimate": "22/3", "unseen": "4/3"})

    planner, sources = planner_fixture(domain)
    duplicate = planner.source_value(sources[q(domain, "duplicate_source")], [q(domain, "known")])
    add("overlap_adjusted_marginal", duplicate.expected_valid_observations == 4 and duplicate.expected_unique_gain == 1 and duplicate.expected_duplicate_observations == 3, {"raw_valid": str(duplicate.expected_valid_observations), "unique_gain": str(duplicate.expected_unique_gain), "duplicate_observations": str(duplicate.expected_duplicate_observations)}, "four records yield one new canonical object")

    exhausted = [q(domain, "probe"), q(domain, "duplicate_source"), q(domain, "positive_source")]
    pre_probe = planner.choose_next_source([], exhausted=exhausted)
    rich_world = q(domain, "rich")
    posterior = planner.posterior_after(source_name=q(domain, "probe"), observed_canonical_ids=[q(domain, "signal_rich")])
    adaptive = DiscoveryPlanner(worlds=planner.worlds, prior=posterior, sources=planner.sources)
    post_probe = adaptive.choose_next_source([], exhausted=exhausted)
    add("adaptive_source_selection", pre_probe is not None and post_probe is not None and pre_probe.source == q(domain, "a_lean_source") and post_probe.source == q(domain, "z_rich_source") and posterior[rich_world] == 1, {"before": None if pre_probe is None else pre_probe.source, "posterior": {k: str(v) for k, v in posterior.items()}, "after": None if post_probe is None else post_probe.source}, "a discriminating probe changes the optimal next source")

    known = {q(domain, "known")}
    remaining = planner.rank_sources(known, exhausted=[q(domain, "probe"), q(domain, "duplicate_source"), q(domain, "a_lean_source"), q(domain, "z_rich_source")])
    cert = completion_certificate(inventory=DiscoveryInventory([obs(domain, "seed", "known", "known")]), remaining_source_values=remaining)
    add("denominator_blindness", cert.status == "CONTINUE_POSITIVE_VALUE" and q(domain, "positive_source") in cert.witnesses, {"baseline_stop": True, "certificate": cert.to_dict()}, "zero gain from one source cannot prove global completion")

    exact_inventory = DiscoveryInventory([obs(domain, "exact", "1", "a"), obs(domain, "exact", "2", "b"), obs(domain, "exact", "3", "c"), obs(domain, "exact", "4", "d")])
    exact_cert = completion_certificate(inventory=exact_inventory, authoritative_total=4)
    saturated_inventory = DiscoveryInventory([obs(domain, "sat", "1", "a"), obs(domain, "sat", "2", "a"), obs(domain, "sat", "3", "b"), obs(domain, "sat", "4", "b")])
    estimated_cert = completion_certificate(inventory=saturated_inventory, remaining_source_values=[])
    add("honest_stopping", exact_cert.status == "EXACT_COMPLETE" and exact_cert.exact and estimated_cert.status == "ESTIMATED_SATURATED" and not estimated_cert.exact, {"exact": exact_cert.to_dict(), "estimated": estimated_cert.to_dict()}, "exact and estimated completion are never conflated")

    complete_world, incomplete_world = q(domain, "complete"), q(domain, "incomplete")
    indistinguishable = DiscoverySource(q(domain, "allowed_probe"), 1, {complete_world: [obs(domain, "probe2", "1", "same")], incomplete_world: [obs(domain, "probe2", "1", "same")]})
    impossible = impossibility_certificate(complete_world=complete_world, incomplete_world=incomplete_world, sources=[indistinguishable])
    add("impossibility_certificate", impossible is not None and impossible.identical_observations and impossible.world_complete == complete_world and impossible.world_incomplete == incomplete_world, None if impossible is None else impossible.__dict__, "indistinguishable complete/incomplete worlds certify impossibility")

    diff = compare_snapshots({q(domain, "a"): "h1", q(domain, "b"): "h2", q(domain, "c"): "h3"}, {q(domain, "b"): "h2_new", q(domain, "c"): "h3", q(domain, "d"): "h4"})
    add("snapshot_drift", diff.added == (q(domain, "d"),) and diff.removed == (q(domain, "a"),) and diff.modified == (q(domain, "b"),) and diff.unchanged == (q(domain, "c"),), diff.__dict__, "added, removed, modified and unchanged separated")

    aggregate = aggregate_fixture(domain)
    expected_missing = 40_283 if domain == "governance" else 5 + DOMAINS.index(domain)
    add("aggregate_real_diagnostic", aggregate.known_missing_files == expected_missing and aggregate.status == "CONTINUE_KNOWN_GAP" and set(aggregate.missing_inputs_for_unseen_estimation) == {"frequency_of_frequencies_f1_f2", "independent_source_capture_overlap"}, aggregate.to_dict(), {"known_missing": expected_missing, "unseen_estimation": "blocked until f1/f2 and capture overlaps exist"})
    assert tuple(row["archetype"] for row in rows) == ARCHETYPES
    return rows


def run_benchmark(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [row for domain in DOMAINS for row in check_domain(domain)]
    passed = sum(1 for row in rows if row["passed"])
    manifest = {"schema": "open-world-discovery-power/manifest/1", "domains": list(DOMAINS), "archetypes": list(ARCHETYPES), "scenario_ids": [f"{row['domain']}::{row['archetype']}" for row in rows]}
    summary = {"schema": "open-world-discovery-power/benchmark-summary/1", "scenario_count": len(rows), "passed": passed, "failed": len(rows) - passed, "exact_conformance": passed / len(rows), "rows_sha256": digest(rows)}
    matrix_path = out / "benchmark_matrix.csv"
    with matrix_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("domain", "archetype", "passed", "observed", "expected"))
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "observed": json.dumps(row["observed"], sort_keys=True, ensure_ascii=False, default=str), "expected": json.dumps(row["expected"], sort_keys=True, ensure_ascii=False, default=str)})
    (out / "scenario_manifest.json").write_bytes(canonical_json(manifest) + b"\n")
    (out / "benchmark_summary.json").write_bytes(canonical_json(summary) + b"\n")
    iaip = aggregate_fixture("governance")
    (out / "iaip_aggregate_diagnostic.json").write_bytes(canonical_json(iaip.to_dict()) + b"\n")
    payload = {"status": "PASS" if passed == len(rows) else "FAIL", "scenario_count": len(rows), "passed": passed, "manifest_sha256": hashlib.sha256((out / "scenario_manifest.json").read_bytes()).hexdigest(), "summary_sha256": hashlib.sha256((out / "benchmark_summary.json").read_bytes()).hexdigest(), "matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(), "iaip_diagnostic_sha256": hashlib.sha256((out / "iaip_aggregate_diagnostic.json").read_bytes()).hexdigest()}
    receipt = discovery_receipt(payload)
    (out / "benchmark_receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return {"rows": rows, "manifest": manifest, "summary": summary, "receipt": receipt, "iaip": iaip}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports")
    args = parser.parse_args()
    result = run_benchmark(args.output)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
