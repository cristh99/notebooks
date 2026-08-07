"""Exact finite open-world discovery power.

Discovery power is the verified capacity to enlarge and certify a known universe:
acquire distinct valid objects, estimate residual unseen mass, choose probes by
marginal unique value, and stop only with an exact, estimated, or impossibility
certificate.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Mapping
import hashlib
import json


def F(value: int | float | str | Fraction | tuple[int, int]) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, tuple):
        return Fraction(value[0], value[1])
    if isinstance(value, float):
        return Fraction(str(value))
    return Fraction(value)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True, order=True)
class Observation:
    source: str
    record_id: str
    canonical_id: str
    content_hash: str
    valid: bool = True

    def __init__(self, source: str, record_id: str, canonical_id: str, content_hash: str, valid: bool = True) -> None:
        object.__setattr__(self, "source", str(source))
        object.__setattr__(self, "record_id", str(record_id))
        object.__setattr__(self, "canonical_id", str(canonical_id))
        object.__setattr__(self, "content_hash", str(content_hash))
        object.__setattr__(self, "valid", bool(valid))


@dataclass(frozen=True)
class InventoryStats:
    observation_count: int
    valid_observation_count: int
    invalid_observation_count: int
    observed_unique: int
    duplicate_observations: int
    singleton_count: int
    doubleton_count: int
    sample_coverage: Fraction
    missing_mass: Fraction
    chao_lower_bound: Fraction
    chao_unseen_estimate: Fraction

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_count": self.observation_count,
            "valid_observation_count": self.valid_observation_count,
            "invalid_observation_count": self.invalid_observation_count,
            "observed_unique": self.observed_unique,
            "duplicate_observations": self.duplicate_observations,
            "singleton_count": self.singleton_count,
            "doubleton_count": self.doubleton_count,
            "sample_coverage": [self.sample_coverage.numerator, self.sample_coverage.denominator],
            "missing_mass": [self.missing_mass.numerator, self.missing_mass.denominator],
            "chao_lower_bound": [self.chao_lower_bound.numerator, self.chao_lower_bound.denominator],
            "chao_unseen_estimate": [self.chao_unseen_estimate.numerator, self.chao_unseen_estimate.denominator],
        }


class DiscoveryInventory:
    def __init__(self, observations: Iterable[Observation] = ()) -> None:
        self.observations = tuple(sorted(observations))

    def valid_observations(self) -> tuple[Observation, ...]:
        return tuple(o for o in self.observations if o.valid)

    def canonical_items(self) -> frozenset[str]:
        return frozenset(o.canonical_id for o in self.valid_observations())

    def frequencies(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for obs in self.valid_observations():
            counts[obs.canonical_id] = counts.get(obs.canonical_id, 0) + 1
        return dict(sorted(counts.items()))

    def stats(self) -> InventoryStats:
        valid = self.valid_observations()
        frequencies = self.frequencies()
        n = len(valid)
        s_obs = len(frequencies)
        f1 = sum(1 for count in frequencies.values() if count == 1)
        f2 = sum(1 for count in frequencies.values() if count == 2)
        coverage = Fraction(1) if n == 0 else max(Fraction(), Fraction(1) - Fraction(f1, n))
        missing_mass = Fraction() if n == 0 else Fraction(f1, n)
        unseen = Fraction(f1 * max(0, f1 - 1), 2 * (f2 + 1))
        return InventoryStats(
            observation_count=len(self.observations),
            valid_observation_count=n,
            invalid_observation_count=len(self.observations) - n,
            observed_unique=s_obs,
            duplicate_observations=max(0, n - s_obs),
            singleton_count=f1,
            doubleton_count=f2,
            sample_coverage=coverage,
            missing_mass=missing_mass,
            chao_lower_bound=Fraction(s_obs) + unseen,
            chao_unseen_estimate=unseen,
        )


def chapman_population_estimate(list_a: Iterable[str], list_b: Iterable[str]) -> Fraction:
    a = set(map(str, list_a))
    b = set(map(str, list_b))
    overlap = len(a & b)
    return Fraction((len(a) + 1) * (len(b) + 1), overlap + 1) - 1


@dataclass(frozen=True)
class DiscoverySource:
    name: str
    cost: int
    outcomes_by_world: tuple[tuple[str, tuple[Observation, ...]], ...]
    allowed: bool = True
    blocked_reason: str | None = None

    def __init__(self, name: str, cost: int, outcomes_by_world: Mapping[str, Iterable[Observation]], *, allowed: bool = True, blocked_reason: str | None = None) -> None:
        if int(cost) <= 0:
            raise ValueError("source cost must be positive")
        object.__setattr__(self, "name", str(name))
        object.__setattr__(self, "cost", int(cost))
        object.__setattr__(self, "outcomes_by_world", tuple(sorted((str(world), tuple(sorted(observations))) for world, observations in outcomes_by_world.items())))
        object.__setattr__(self, "allowed", bool(allowed))
        object.__setattr__(self, "blocked_reason", None if blocked_reason is None else str(blocked_reason))

    def observations(self, world: str) -> tuple[Observation, ...]:
        mapping = dict(self.outcomes_by_world)
        if world not in mapping:
            raise KeyError(world)
        return mapping[world]


@dataclass(frozen=True)
class SourceValue:
    source: str
    expected_unique_gain: Fraction
    robust_unique_gain: int
    expected_gain_per_cost: Fraction
    expected_valid_observations: Fraction
    expected_duplicate_observations: Fraction


class DiscoveryPlanner:
    def __init__(self, *, worlds: Iterable[str], prior: Mapping[str, int | float | str | Fraction | tuple[int, int]], sources: Iterable[DiscoverySource]) -> None:
        self.worlds = tuple(sorted(set(map(str, worlds))))
        if not self.worlds:
            raise ValueError("at least one world is required")
        self.prior = {str(k): F(v) for k, v in prior.items()}
        if set(self.prior) != set(self.worlds):
            raise ValueError("prior must cover exactly the worlds")
        if sum(self.prior.values(), Fraction()) != 1:
            raise ValueError("prior must sum to one")
        self.sources = tuple(sorted(sources, key=lambda s: s.name))

    @staticmethod
    def _source_gain(source: DiscoverySource, world: str, known: frozenset[str]) -> tuple[int, int, int]:
        valid = [o for o in source.observations(world) if o.valid]
        unique_new = {o.canonical_id for o in valid} - set(known)
        return len(unique_new), len(valid), len(valid) - len(unique_new)

    def source_value(self, source: DiscoverySource, known: Iterable[str]) -> SourceValue:
        known_set = frozenset(map(str, known))
        expected_gain = Fraction()
        expected_valid = Fraction()
        expected_duplicates = Fraction()
        robust_gain: int | None = None
        for world in self.worlds:
            gain, valid, duplicates = self._source_gain(source, world, known_set)
            p = self.prior[world]
            expected_gain += p * gain
            expected_valid += p * valid
            expected_duplicates += p * duplicates
            robust_gain = gain if robust_gain is None else min(robust_gain, gain)
        return SourceValue(source.name, expected_gain, robust_gain or 0, expected_gain / source.cost, expected_valid, expected_duplicates)

    def rank_sources(self, known: Iterable[str], *, exhausted: Iterable[str] = ()) -> tuple[SourceValue, ...]:
        exhausted_set = set(map(str, exhausted))
        values = [self.source_value(source, known) for source in self.sources if source.allowed and source.name not in exhausted_set]
        return tuple(sorted(values, key=lambda value: (-value.expected_gain_per_cost, -value.robust_unique_gain, -value.expected_unique_gain, value.source)))

    def choose_next_source(self, known: Iterable[str], *, exhausted: Iterable[str] = ()) -> SourceValue | None:
        ranked = self.rank_sources(known, exhausted=exhausted)
        return None if not ranked else ranked[0]

    def posterior_after(self, *, source_name: str, observed_canonical_ids: Iterable[str]) -> dict[str, Fraction]:
        source = next(s for s in self.sources if s.name == source_name)
        observed = frozenset(map(str, observed_canonical_ids))
        weights: dict[str, Fraction] = {}
        for world in self.worlds:
            predicted = frozenset(o.canonical_id for o in source.observations(world) if o.valid)
            weights[world] = self.prior[world] if predicted == observed else Fraction()
        total = sum(weights.values(), Fraction())
        if total == 0:
            raise ValueError("observation is impossible under all declared worlds")
        return {world: weight / total for world, weight in weights.items()}


@dataclass(frozen=True)
class CompletionCertificate:
    status: str
    exact: bool
    observed_unique: int
    known_gap: int
    estimated_unseen: Fraction
    sample_coverage: Fraction
    reason: str
    witnesses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "exact": self.exact,
            "observed_unique": self.observed_unique,
            "known_gap": self.known_gap,
            "estimated_unseen": [self.estimated_unseen.numerator, self.estimated_unseen.denominator],
            "sample_coverage": [self.sample_coverage.numerator, self.sample_coverage.denominator],
            "reason": self.reason,
            "witnesses": list(self.witnesses),
        }


def completion_certificate(*, inventory: DiscoveryInventory, authoritative_total: int | None = None, known_unresolved_ids: Iterable[str] = (), remaining_source_values: Iterable[SourceValue] = (), coverage_threshold: Fraction = Fraction(99, 100), max_estimated_unseen: Fraction = Fraction(1), indistinguishable_complete_incomplete_worlds: tuple[str, str] | None = None, blocked_sources: Iterable[DiscoverySource] = ()) -> CompletionCertificate:
    stats = inventory.stats()
    unresolved = tuple(sorted(set(map(str, known_unresolved_ids))))
    known_gap = len(unresolved)
    if authoritative_total is not None:
        if authoritative_total < stats.observed_unique:
            return CompletionCertificate("INCONSISTENT_DENOMINATOR", False, stats.observed_unique, known_gap, stats.chao_unseen_estimate, stats.sample_coverage, "authoritative total is below observed unique count")
        denominator_gap = authoritative_total - stats.observed_unique
        if denominator_gap == 0 and known_gap == 0:
            return CompletionCertificate("EXACT_COMPLETE", True, stats.observed_unique, 0, Fraction(), Fraction(1), "authoritative denominator matched and no unresolved identifiers remain")
        return CompletionCertificate("CONTINUE_KNOWN_GAP", True, stats.observed_unique, max(known_gap, denominator_gap), stats.chao_unseen_estimate, stats.sample_coverage, "an authoritative denominator exposes unresolved or missing objects", unresolved)
    if known_gap:
        return CompletionCertificate("CONTINUE_KNOWN_GAP", False, stats.observed_unique, known_gap, stats.chao_unseen_estimate, stats.sample_coverage, "known identifiers remain unresolved", unresolved)
    blocked = tuple(sorted(source.name for source in blocked_sources if not source.allowed))
    if blocked:
        return CompletionCertificate("BLOCKED_SOURCE", False, stats.observed_unique, 0, stats.chao_unseen_estimate, stats.sample_coverage, "one or more sources required for broader coverage are not admissible", blocked)
    if indistinguishable_complete_incomplete_worlds is not None:
        return CompletionCertificate("IMPOSSIBLE_TO_CERTIFY", False, stats.observed_unique, 0, stats.chao_unseen_estimate, stats.sample_coverage, "allowed observations cannot distinguish a complete world from an incomplete world", tuple(indistinguishable_complete_incomplete_worlds))
    remaining = tuple(remaining_source_values)
    if any(value.expected_unique_gain > 0 for value in remaining):
        return CompletionCertificate("CONTINUE_POSITIVE_VALUE", False, stats.observed_unique, 0, stats.chao_unseen_estimate, stats.sample_coverage, "an admissible source has positive expected marginal unique gain", tuple(value.source for value in remaining if value.expected_unique_gain > 0))
    if stats.sample_coverage >= coverage_threshold and stats.chao_unseen_estimate <= max_estimated_unseen:
        return CompletionCertificate("ESTIMATED_SATURATED", False, stats.observed_unique, 0, stats.chao_unseen_estimate, stats.sample_coverage, "coverage and unseen-mass thresholds passed, but no exact denominator exists")
    return CompletionCertificate("CONTINUE_ESTIMATED_UNSEEN", False, stats.observed_unique, 0, stats.chao_unseen_estimate, stats.sample_coverage, "frequency-of-frequencies indicates residual unseen mass")


@dataclass(frozen=True)
class ImpossibilityCertificate:
    world_complete: str
    world_incomplete: str
    allowed_sources: tuple[str, ...]
    identical_observations: bool
    reason: str


def impossibility_certificate(*, complete_world: str, incomplete_world: str, sources: Iterable[DiscoverySource]) -> ImpossibilityCertificate | None:
    allowed = tuple(source for source in sources if source.allowed)
    identical = all(frozenset(o.canonical_id for o in source.observations(complete_world) if o.valid) == frozenset(o.canonical_id for o in source.observations(incomplete_world) if o.valid) for source in allowed)
    if not identical:
        return None
    return ImpossibilityCertificate(complete_world, incomplete_world, tuple(source.name for source in allowed), True, "every allowed source yields the same canonical observations in both worlds")


@dataclass(frozen=True)
class SnapshotDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]
    unchanged: tuple[str, ...]


def compare_snapshots(before: Mapping[str, str], after: Mapping[str, str]) -> SnapshotDiff:
    before_map = {str(k): str(v) for k, v in before.items()}
    after_map = {str(k): str(v) for k, v in after.items()}
    before_ids = set(before_map)
    after_ids = set(after_map)
    common = before_ids & after_ids
    return SnapshotDiff(tuple(sorted(after_ids - before_ids)), tuple(sorted(before_ids - after_ids)), tuple(sorted(i for i in common if before_map[i] != after_map[i])), tuple(sorted(i for i in common if before_map[i] == after_map[i])))


@dataclass(frozen=True)
class AggregateDiagnostic:
    declared_records: int
    declared_document_urls: int
    physical_files: int
    non_document_links: int
    known_missing_files: int
    url_coverage: Fraction
    physical_coverage: Fraction
    status: str
    missing_inputs_for_unseen_estimation: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "declared_records": self.declared_records,
            "declared_document_urls": self.declared_document_urls,
            "physical_files": self.physical_files,
            "non_document_links": self.non_document_links,
            "known_missing_files": self.known_missing_files,
            "url_coverage": [self.url_coverage.numerator, self.url_coverage.denominator],
            "physical_coverage": [self.physical_coverage.numerator, self.physical_coverage.denominator],
            "status": self.status,
            "missing_inputs_for_unseen_estimation": list(self.missing_inputs_for_unseen_estimation),
        }


def aggregate_diagnostic(*, declared_records: int, declared_document_urls: int, physical_files: int, non_document_links: int, has_frequency_of_frequencies: bool = False, has_independent_capture_lists: bool = False) -> AggregateDiagnostic:
    if min(declared_records, declared_document_urls, physical_files, non_document_links) < 0:
        raise ValueError("counts must be non-negative")
    if declared_document_urls > declared_records:
        raise ValueError("document URLs cannot exceed records")
    if physical_files > declared_document_urls:
        raise ValueError("physical files cannot exceed document URLs")
    known_missing = declared_document_urls - physical_files
    missing_inputs = []
    if not has_frequency_of_frequencies:
        missing_inputs.append("frequency_of_frequencies_f1_f2")
    if not has_independent_capture_lists:
        missing_inputs.append("independent_source_capture_overlap")
    status = "CONTINUE_KNOWN_GAP" if known_missing > 0 else ("BLOCKED_UNSEEN_ESTIMATION" if missing_inputs else "ESTIMABLE")
    return AggregateDiagnostic(declared_records, declared_document_urls, physical_files, non_document_links, known_missing, Fraction(declared_document_urls, declared_records) if declared_records else Fraction(), Fraction(physical_files, declared_document_urls) if declared_document_urls else Fraction(), status, tuple(missing_inputs))


def discovery_receipt(payload: Mapping[str, object]) -> dict[str, object]:
    body = {"schema": "open-world-discovery-power/receipt/1", "payload": payload}
    return {**body, "sha256": digest(body)}


def verify_discovery_receipt(receipt: Mapping[str, object]) -> bool:
    if receipt.get("schema") != "open-world-discovery-power/receipt/1":
        return False
    body = {"schema": receipt["schema"], "payload": receipt.get("payload")}
    return receipt.get("sha256") == digest(body)
