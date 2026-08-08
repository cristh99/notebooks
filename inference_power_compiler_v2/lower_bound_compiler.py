from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import product
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


def total_variation(
    left: Sequence[Fraction], right: Sequence[Fraction]
) -> Fraction:
    if len(left) != len(right):
        raise ValueError("distributions must have the same support")
    validate_distribution(left)
    validate_distribution(right)
    return sum(
        (abs(left[index] - right[index]) for index in range(len(left))),
        Fraction(0),
    ) / 2


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
class FiniteEstimationProblem:
    worlds: tuple[str, ...]
    outcomes: tuple[str, ...]
    laws: Mapping[str, tuple[Fraction, ...]]
    targets: Mapping[str, tuple[Fraction, ...]]

    def __post_init__(self) -> None:
        if not self.worlds or len(set(self.worlds)) != len(self.worlds):
            raise ValueError("worlds must be nonempty and unique")
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
                raise ValueError("targets must be nonempty vectors")
            if target_dimension is None:
                target_dimension = len(target)
            elif len(target) != target_dimension:
                raise ValueError("all targets must have equal dimension")

    def to_data(self) -> dict[str, object]:
        return {
            "worlds": list(self.worlds),
            "outcomes": list(self.outcomes),
            "laws": {
                world: [fraction_data(value) for value in self.laws[world]]
                for world in sorted(self.worlds)
            },
            "targets": {
                world: [fraction_data(value) for value in self.targets[world]]
                for world in sorted(self.worlds)
            },
        }

    @classmethod
    def from_data(
        cls, data: Mapping[str, object]
    ) -> "FiniteEstimationProblem":
        worlds = data.get("worlds")
        outcomes = data.get("outcomes")
        laws_data = data.get("laws")
        targets_data = data.get("targets")
        if (
            not isinstance(worlds, list)
            or not all(isinstance(world, str) for world in worlds)
            or not isinstance(outcomes, list)
            or not all(isinstance(outcome, str) for outcome in outcomes)
            or not isinstance(laws_data, Mapping)
            or not isinstance(targets_data, Mapping)
        ):
            raise ValueError("malformed finite estimation problem")
        laws: dict[str, tuple[Fraction, ...]] = {}
        targets: dict[str, tuple[Fraction, ...]] = {}
        for world in worlds:
            raw_law = laws_data.get(world)
            raw_target = targets_data.get(world)
            if not isinstance(raw_law, list) or not isinstance(
                raw_target, list
            ):
                raise ValueError("malformed law or target")
            laws[world] = tuple(parse_fraction(value) for value in raw_law)
            targets[world] = tuple(
                parse_fraction(value) for value in raw_target
            )
        return cls(
            worlds=tuple(worlds),
            outcomes=tuple(outcomes),
            laws=laws,
            targets=targets,
        )


def strongest_le_cam_pair(
    problem: FiniteEstimationProblem,
) -> dict[str, object]:
    """Compile the strongest two-point squared-loss lower bound.

    For a pair with squared target separation Delta^2 and total variation TV,
    the event reduction gives max risk >= Delta^2(1-TV)/8.
    """

    pairs: list[dict[str, object]] = []
    best: tuple[Fraction, str, str] | None = None
    for left_index, left in enumerate(problem.worlds):
        for right in problem.worlds[left_index + 1 :]:
            delta_sq = squared_distance(
                problem.targets[left], problem.targets[right]
            )
            tv = total_variation(problem.laws[left], problem.laws[right])
            overlap = 1 - tv
            bound = delta_sq * overlap / 8
            entry = {
                "left": left,
                "right": right,
                "squared_target_separation": fraction_data(delta_sq),
                "total_variation": fraction_data(tv),
                "overlap": fraction_data(overlap),
                "lower_bound": fraction_data(bound),
            }
            pairs.append(entry)
            candidate = (bound, left, right)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        raise ValueError("at least two worlds are required")
    best_bound, best_left, best_right = best
    witness = next(
        entry
        for entry in pairs
        if entry["left"] == best_left and entry["right"] == best_right
    )
    return {
        "method": "Le Cam two-point event reduction",
        "loss": "squared Euclidean",
        "pair_count": len(pairs),
        "witness": witness,
        "strongest_lower_bound": fraction_data(best_bound),
        "all_pairs": pairs,
    }


def build_le_cam_certificate(
    problem: FiniteEstimationProblem, case_name: str
) -> dict[str, object]:
    payload = {
        "schema": "inference-power-compiler/le-cam-certificate/1",
        "case": case_name,
        "problem": problem.to_data(),
        "result": strongest_le_cam_pair(problem),
    }
    return {"payload": payload, "sha256": digest_payload(payload)}


def verify_le_cam_certificate(
    certificate: Mapping[str, object],
) -> list[str]:
    payload = certificate.get("payload")
    payload_hash = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(payload_hash, str):
        return ["certificate-shape"]
    if digest_payload(payload) != payload_hash:
        return ["payload-hash"]
    try:
        problem_data = payload.get("problem")
        case_name = payload.get("case")
        if not isinstance(problem_data, Mapping) or not isinstance(
            case_name, str
        ):
            raise ValueError("malformed payload")
        problem = FiniteEstimationProblem.from_data(problem_data)
        rebuilt = build_le_cam_certificate(problem, case_name)
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    if canonical_json(rebuilt["payload"]) != canonical_json(payload):
        return ["semantic-replay"]
    return []


def bitstrings(dimension: int) -> tuple[str, ...]:
    if dimension <= 0:
        raise ValueError("dimension must be positive")
    return tuple(
        "".join(str(bit) for bit in bits)
        for bits in product((0, 1), repeat=dimension)
    )


def hamming(left: str, right: str) -> int:
    if len(left) != len(right):
        raise ValueError("bitstrings must have equal length")
    return sum(a != b for a, b in zip(left, right))


@dataclass(frozen=True)
class HypercubeExperiment:
    dimension: int
    crossover: Fraction
    worlds: tuple[str, ...]
    outcomes: tuple[str, ...]
    laws: Mapping[str, tuple[Fraction, ...]]

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            raise ValueError("dimension must be positive")
        if not (0 <= self.crossover <= Fraction(1, 2)):
            raise ValueError("crossover must lie in [0,1/2]")
        expected = bitstrings(self.dimension)
        if self.worlds != expected or self.outcomes != expected:
            raise ValueError("worlds and outcomes must be the full hypercube")
        if set(self.laws) != set(expected):
            raise ValueError("laws must cover the hypercube")
        for law in self.laws.values():
            if len(law) != len(expected):
                raise ValueError("law length mismatch")
            validate_distribution(law)

    def to_data(self) -> dict[str, object]:
        return {
            "dimension": self.dimension,
            "crossover": fraction_data(self.crossover),
            "worlds": list(self.worlds),
            "outcomes": list(self.outcomes),
            "laws": {
                world: [fraction_data(value) for value in self.laws[world]]
                for world in self.worlds
            },
        }

    @classmethod
    def from_data(
        cls, data: Mapping[str, object]
    ) -> "HypercubeExperiment":
        dimension = data.get("dimension")
        worlds = data.get("worlds")
        outcomes = data.get("outcomes")
        laws_data = data.get("laws")
        if (
            not isinstance(dimension, int)
            or not isinstance(worlds, list)
            or not all(isinstance(value, str) for value in worlds)
            or not isinstance(outcomes, list)
            or not all(isinstance(value, str) for value in outcomes)
            or not isinstance(laws_data, Mapping)
        ):
            raise ValueError("malformed hypercube experiment")
        laws: dict[str, tuple[Fraction, ...]] = {}
        for world in worlds:
            raw = laws_data.get(world)
            if not isinstance(raw, list):
                raise ValueError("malformed hypercube law")
            laws[world] = tuple(parse_fraction(value) for value in raw)
        return cls(
            dimension=dimension,
            crossover=parse_fraction(data.get("crossover")),
            worlds=tuple(worlds),
            outcomes=tuple(outcomes),
            laws=laws,
        )


def make_binary_symmetric_hypercube(
    dimension: int, crossover: Fraction
) -> HypercubeExperiment:
    strings = bitstrings(dimension)
    laws: dict[str, tuple[Fraction, ...]] = {}
    for world in strings:
        probabilities = []
        for outcome in strings:
            errors = hamming(world, outcome)
            probabilities.append(
                crossover**errors
                * (1 - crossover) ** (dimension - errors)
            )
        laws[world] = tuple(probabilities)
    return HypercubeExperiment(
        dimension=dimension,
        crossover=crossover,
        worlds=strings,
        outcomes=strings,
        laws=laws,
    )


def mixture_law(
    experiment: HypercubeExperiment, worlds: Sequence[str]
) -> tuple[Fraction, ...]:
    if not worlds:
        raise ValueError("mixture requires at least one world")
    weight = Fraction(1, len(worlds))
    return tuple(
        sum(
            (
                weight * experiment.laws[world][outcome_index]
                for world in worlds
            ),
            Fraction(0),
        )
        for outcome_index in range(len(experiment.outcomes))
    )


def identity_decoder_risks(
    experiment: HypercubeExperiment,
) -> tuple[Fraction, ...]:
    return tuple(
        sum(
            (
                experiment.laws[world][outcome_index]
                * hamming(world, outcome)
                for outcome_index, outcome in enumerate(
                    experiment.outcomes
                )
            ),
            Fraction(0),
        )
        for world in experiment.worlds
    )


def assouad_hamming_bound(
    experiment: HypercubeExperiment,
) -> dict[str, object]:
    coordinates: list[dict[str, object]] = []
    lower = Fraction(0)
    for coordinate in range(experiment.dimension):
        zero_worlds = tuple(
            world for world in experiment.worlds if world[coordinate] == "0"
        )
        one_worlds = tuple(
            world for world in experiment.worlds if world[coordinate] == "1"
        )
        zero_mix = mixture_law(experiment, zero_worlds)
        one_mix = mixture_law(experiment, one_worlds)
        tv = total_variation(zero_mix, one_mix)
        coordinate_bound = (1 - tv) / 2
        lower += coordinate_bound
        coordinates.append(
            {
                "coordinate": coordinate,
                "mixture_zero_size": len(zero_worlds),
                "mixture_one_size": len(one_worlds),
                "total_variation": fraction_data(tv),
                "coordinate_lower_bound": fraction_data(coordinate_bound),
            }
        )
    risks = identity_decoder_risks(experiment)
    upper = max(risks)
    return {
        "method": "Assouad hypercube mixture reduction",
        "loss": "Hamming",
        "coordinate_certificates": coordinates,
        "lower_bound": fraction_data(lower),
        "identity_decoder_risks": [fraction_data(value) for value in risks],
        "identity_decoder_upper_bound": fraction_data(upper),
        "matched": lower == upper,
        "exact_minimax_value": (
            fraction_data(lower) if lower == upper else None
        ),
    }


def build_assouad_certificate(
    experiment: HypercubeExperiment, case_name: str
) -> dict[str, object]:
    payload = {
        "schema": "inference-power-compiler/assouad-certificate/1",
        "case": case_name,
        "experiment": experiment.to_data(),
        "result": assouad_hamming_bound(experiment),
    }
    return {"payload": payload, "sha256": digest_payload(payload)}


def verify_assouad_certificate(
    certificate: Mapping[str, object],
) -> list[str]:
    payload = certificate.get("payload")
    payload_hash = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(payload_hash, str):
        return ["certificate-shape"]
    if digest_payload(payload) != payload_hash:
        return ["payload-hash"]
    try:
        experiment_data = payload.get("experiment")
        case_name = payload.get("case")
        if not isinstance(experiment_data, Mapping) or not isinstance(
            case_name, str
        ):
            raise ValueError("malformed payload")
        experiment = HypercubeExperiment.from_data(experiment_data)
        rebuilt = build_assouad_certificate(experiment, case_name)
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    if canonical_json(rebuilt["payload"]) != canonical_json(payload):
        return ["semantic-replay"]
    return []
