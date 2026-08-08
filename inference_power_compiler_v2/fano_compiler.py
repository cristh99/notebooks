from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
import json
from typing import Mapping, Sequence


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def digest_payload(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def fraction_data(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def parse_fraction(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("fraction must be [numerator, denominator]")
    numerator, denominator = value
    if (
        not isinstance(numerator, int)
        or not isinstance(denominator, int)
        or denominator <= 0
    ):
        raise ValueError("invalid rational")
    return Fraction(numerator, denominator)


def validate_distribution(values: Sequence[Fraction]) -> None:
    if not values:
        raise ValueError("distribution must be nonempty")
    if any(value < 0 for value in values):
        raise ValueError("probabilities must be nonnegative")
    if sum(values, Fraction(0)) != 1:
        raise ValueError("probabilities must sum exactly to one")


@dataclass(frozen=True)
class RationalInterval:
    lower: Fraction
    upper: Fraction

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError("interval lower bound exceeds upper bound")

    def to_data(self) -> dict[str, list[int]]:
        return {
            "lower": fraction_data(self.lower),
            "upper": fraction_data(self.upper),
        }

    def __add__(self, other: "RationalInterval | Fraction | int") -> "RationalInterval":
        if isinstance(other, RationalInterval):
            return RationalInterval(
                self.lower + other.lower, self.upper + other.upper
            )
        value = Fraction(other)
        return RationalInterval(self.lower + value, self.upper + value)

    __radd__ = __add__

    def __sub__(self, other: "RationalInterval | Fraction | int") -> "RationalInterval":
        if isinstance(other, RationalInterval):
            return RationalInterval(
                self.lower - other.upper, self.upper - other.lower
            )
        value = Fraction(other)
        return RationalInterval(self.lower - value, self.upper - value)

    def __mul__(self, other: "RationalInterval | Fraction | int") -> "RationalInterval":
        if isinstance(other, RationalInterval):
            candidates = (
                self.lower * other.lower,
                self.lower * other.upper,
                self.upper * other.lower,
                self.upper * other.upper,
            )
            return RationalInterval(min(candidates), max(candidates))
        value = Fraction(other)
        if value >= 0:
            return RationalInterval(self.lower * value, self.upper * value)
        return RationalInterval(self.upper * value, self.lower * value)

    __rmul__ = __mul__

    def __truediv__(self, other: "RationalInterval | Fraction | int") -> "RationalInterval":
        if isinstance(other, RationalInterval):
            if other.lower <= 0 <= other.upper:
                raise ZeroDivisionError("interval denominator contains zero")
            candidates = (
                self.lower / other.lower,
                self.lower / other.upper,
                self.upper / other.lower,
                self.upper / other.upper,
            )
            return RationalInterval(min(candidates), max(candidates))
        value = Fraction(other)
        if value == 0:
            raise ZeroDivisionError
        if value > 0:
            return RationalInterval(self.lower / value, self.upper / value)
        return RationalInterval(self.upper / value, self.lower / value)


def _log_interval_basic(value: Fraction, terms: int) -> RationalInterval:
    if value <= 0:
        raise ValueError("log requires a positive rational")
    if value == 1:
        return RationalInterval(Fraction(0), Fraction(0))
    y = (value - 1) / (value + 1)
    y_squared = y * y
    power = y
    partial = Fraction(0)
    for index in range(terms):
        partial += power / Fraction(2 * index + 1)
        power *= y_squared
    partial *= 2
    absolute_y = abs(y)
    remainder = (
        2
        * absolute_y ** (2 * terms + 1)
        / (
            Fraction(2 * terms + 1)
            * (1 - absolute_y * absolute_y)
        )
    )
    return RationalInterval(partial - remainder, partial + remainder)


def log_interval(value: Fraction, terms: int = 24) -> RationalInterval:
    if value <= 0:
        raise ValueError("log requires a positive rational")
    reduced = value
    exponent = 0
    while reduced >= 2:
        reduced /= 2
        exponent += 1
    while reduced < 1:
        reduced *= 2
        exponent -= 1
    return (
        _log_interval_basic(reduced, terms)
        + exponent * _log_interval_basic(Fraction(2), terms)
    )


def rational_floor(value: Fraction, denominator: int = 10**12) -> Fraction:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    scaled = value * denominator
    return Fraction(scaled.numerator // scaled.denominator, denominator)


def squared_distance(
    left: Sequence[Fraction], right: Sequence[Fraction]
) -> Fraction:
    if len(left) != len(right):
        raise ValueError("target vectors must have equal dimension")
    return sum(
        ((left[index] - right[index]) ** 2 for index in range(len(left))),
        Fraction(0),
    )


@dataclass(frozen=True)
class FiniteFanoProblem:
    worlds: tuple[str, ...]
    outcomes: tuple[str, ...]
    laws: Mapping[str, tuple[Fraction, ...]]
    targets: Mapping[str, tuple[Fraction, ...]]
    log_terms: int = 24

    def __post_init__(self) -> None:
        if len(self.worlds) < 2 or len(set(self.worlds)) != len(self.worlds):
            raise ValueError("at least two unique worlds are required")
        if len(self.worlds) > 12:
            raise ValueError("exact subset search is limited to twelve worlds")
        if not self.outcomes or len(set(self.outcomes)) != len(self.outcomes):
            raise ValueError("outcomes must be nonempty and unique")
        expected = set(self.worlds)
        if set(self.laws) != expected or set(self.targets) != expected:
            raise ValueError("laws and targets must cover exactly the worlds")
        target_dimension: int | None = None
        for world in self.worlds:
            law = self.laws[world]
            if len(law) != len(self.outcomes):
                raise ValueError("law length must match outcomes")
            validate_distribution(law)
            target = self.targets[world]
            if not target:
                raise ValueError("targets must be nonempty")
            if target_dimension is None:
                target_dimension = len(target)
            elif len(target) != target_dimension:
                raise ValueError("target dimensions differ")
        if self.log_terms < 8:
            raise ValueError("log_terms must be at least eight")

    def to_data(self) -> dict[str, object]:
        return {
            "worlds": list(self.worlds),
            "outcomes": list(self.outcomes),
            "laws": {
                world: [fraction_data(value) for value in self.laws[world]]
                for world in self.worlds
            },
            "targets": {
                world: [fraction_data(value) for value in self.targets[world]]
                for world in self.worlds
            },
            "log_terms": self.log_terms,
        }

    @classmethod
    def from_data(cls, data: Mapping[str, object]) -> "FiniteFanoProblem":
        worlds = data.get("worlds")
        outcomes = data.get("outcomes")
        laws_data = data.get("laws")
        targets_data = data.get("targets")
        log_terms = data.get("log_terms")
        if (
            not isinstance(worlds, list)
            or not all(isinstance(world, str) for world in worlds)
            or not isinstance(outcomes, list)
            or not all(isinstance(outcome, str) for outcome in outcomes)
            or not isinstance(laws_data, Mapping)
            or not isinstance(targets_data, Mapping)
            or not isinstance(log_terms, int)
        ):
            raise ValueError("malformed Fano problem")
        laws: dict[str, tuple[Fraction, ...]] = {}
        targets: dict[str, tuple[Fraction, ...]] = {}
        for world in worlds:
            raw_law = laws_data.get(world)
            raw_target = targets_data.get(world)
            if not isinstance(raw_law, list) or not isinstance(raw_target, list):
                raise ValueError("malformed law or target")
            laws[world] = tuple(parse_fraction(value) for value in raw_law)
            targets[world] = tuple(parse_fraction(value) for value in raw_target)
        return cls(
            worlds=tuple(worlds),
            outcomes=tuple(outcomes),
            laws=laws,
            targets=targets,
            log_terms=log_terms,
        )


def _mixture(
    problem: FiniteFanoProblem, packing: Sequence[str]
) -> tuple[Fraction, ...]:
    weight = Fraction(1, len(packing))
    return tuple(
        sum(
            (weight * problem.laws[world][outcome_index] for world in packing),
            Fraction(0),
        )
        for outcome_index in range(len(problem.outcomes))
    )


def _mutual_information_interval(
    problem: FiniteFanoProblem, packing: Sequence[str]
) -> RationalInterval:
    mixture = _mixture(problem, packing)
    total = RationalInterval(Fraction(0), Fraction(0))
    weight = Fraction(1, len(packing))
    for world in packing:
        for outcome_index, probability in enumerate(problem.laws[world]):
            if probability == 0:
                continue
            reference = mixture[outcome_index]
            total += weight * probability * log_interval(
                probability / reference, problem.log_terms
            )
    if total.lower < 0 and total.upper >= 0:
        return RationalInterval(Fraction(0), total.upper)
    return total


def _packing_result(
    problem: FiniteFanoProblem, packing: Sequence[str]
) -> dict[str, object]:
    pairwise = [
        squared_distance(problem.targets[left], problem.targets[right])
        for left, right in combinations(packing, 2)
    ]
    minimum_squared_separation = min(pairwise)
    radius_squared = minimum_squared_separation / 4
    information = _mutual_information_interval(problem, packing)
    log_two = log_interval(Fraction(2), problem.log_terms)
    log_size = log_interval(Fraction(len(packing)), problem.log_terms)
    numerator = information + log_two
    ratio_upper = numerator.upper / log_size.lower
    ratio_lower = numerator.lower / log_size.upper
    error_lower = max(Fraction(0), 1 - ratio_upper)
    error_upper = min(Fraction(1), max(Fraction(0), 1 - ratio_lower))
    error_interval = RationalInterval(error_lower, error_upper)
    squared_interval = radius_squared * error_interval
    return {
        "packing": list(packing),
        "packing_size": len(packing),
        "minimum_squared_target_separation": fraction_data(minimum_squared_separation),
        "decoding_radius_squared": fraction_data(radius_squared),
        "mutual_information_interval": information.to_data(),
        "log_two_interval": log_two.to_data(),
        "log_packing_size_interval": log_size.to_data(),
        "classification_error_lower_interval": error_interval.to_data(),
        "squared_loss_lower_interval": squared_interval.to_data(),
        "certified_squared_loss_lower_bound": fraction_data(squared_interval.lower),
        "certified_error_floor_1e12": fraction_data(rational_floor(error_interval.lower)),
        "certified_squared_loss_floor_1e12": fraction_data(rational_floor(squared_interval.lower)),
    }


def strongest_fano_packing(problem: FiniteFanoProblem) -> dict[str, object]:
    best: tuple[Fraction, int, tuple[str, ...], dict[str, object]] | None = None
    subsets_examined = 0
    for size in range(2, len(problem.worlds) + 1):
        for packing in combinations(problem.worlds, size):
            subsets_examined += 1
            result = _packing_result(problem, packing)
            lower = parse_fraction(result["certified_squared_loss_lower_bound"])
            candidate = (lower, size, tuple(packing), result)
            if best is None or candidate[0] > best[0] or (
                candidate[0] == best[0]
                and (candidate[1] > best[1] or (
                    candidate[1] == best[1] and candidate[2] < best[2]
                ))
            ):
                best = candidate
    if best is None:
        raise AssertionError("no Fano packing found")
    result = dict(best[3])
    result["subsets_examined"] = subsets_examined
    result["selection_rule"] = (
        "maximize the certified rational squared-loss lower bound; "
        "break ties by larger packing then lexicographic order"
    )
    return result


def map_decoder_upper_bounds(problem: FiniteFanoProblem) -> dict[str, object]:
    decoder: list[str] = []
    for outcome_index in range(len(problem.outcomes)):
        decoder.append(min(
            problem.worlds,
            key=lambda world: (-problem.laws[world][outcome_index], world),
        ))
    classification_risks: list[Fraction] = []
    squared_risks: list[Fraction] = []
    for world in problem.worlds:
        classification_risk = Fraction(0)
        squared_risk = Fraction(0)
        for outcome_index, probability in enumerate(problem.laws[world]):
            chosen = decoder[outcome_index]
            if chosen != world:
                classification_risk += probability
            squared_risk += probability * squared_distance(
                problem.targets[world], problem.targets[chosen]
            )
        classification_risks.append(classification_risk)
        squared_risks.append(squared_risk)
    return {
        "decoder": {problem.outcomes[index]: decoder[index] for index in range(len(problem.outcomes))},
        "classification_risks": [fraction_data(value) for value in classification_risks],
        "maximum_classification_risk": fraction_data(max(classification_risks)),
        "squared_loss_risks": [fraction_data(value) for value in squared_risks],
        "maximum_squared_loss_risk": fraction_data(max(squared_risks)),
    }


def build_fano_certificate(
    problem: FiniteFanoProblem, case_name: str
) -> dict[str, object]:
    payload = {
        "schema": "inference-power-compiler/fano-certificate/1",
        "case": case_name,
        "problem": problem.to_data(),
        "result": {
            "lower_bound": strongest_fano_packing(problem),
            "upper_witness": map_decoder_upper_bounds(problem),
        },
    }
    return {"payload": payload, "sha256": digest_payload(payload)}


def verify_fano_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload = certificate.get("payload")
    payload_hash = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(payload_hash, str):
        return ["certificate-shape"]
    if digest_payload(payload) != payload_hash:
        return ["payload-hash"]
    try:
        problem_data = payload.get("problem")
        case_name = payload.get("case")
        if not isinstance(problem_data, Mapping) or not isinstance(case_name, str):
            raise ValueError("malformed certificate payload")
        rebuilt = build_fano_certificate(
            FiniteFanoProblem.from_data(problem_data), case_name
        )
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    if canonical_json(rebuilt["payload"]) != canonical_json(payload):
        return ["semantic-replay"]
    return []


def make_symmetric_eight_world_problem() -> FiniteFanoProblem:
    worlds = tuple(f"h{index}" for index in range(8))
    outcomes = tuple(f"x{index}" for index in range(8))
    diagonal = Fraction(1, 4)
    off_diagonal = Fraction(3, 28)
    laws = {
        world: tuple(
            diagonal if world_index == outcome_index else off_diagonal
            for outcome_index in range(8)
        )
        for world_index, world in enumerate(worlds)
    }
    targets = {
        world: tuple(
            Fraction(int(world_index == coordinate))
            for coordinate in range(8)
        )
        for world_index, world in enumerate(worlds)
    }
    return FiniteFanoProblem(
        worlds=worlds,
        outcomes=outcomes,
        laws=laws,
        targets=targets,
        log_terms=28,
    )
