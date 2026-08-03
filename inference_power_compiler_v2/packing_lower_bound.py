from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from typing import Mapping, Sequence

from lower_bound_compiler import (
    FiniteEstimationProblem,
    canonical_json,
    digest_payload,
    fraction_data,
    parse_fraction,
    squared_distance,
    validate_distribution,
)


@dataclass(frozen=True)
class FiniteClassificationProblem:
    worlds: tuple[str, ...]
    outcomes: tuple[str, ...]
    laws: Mapping[str, tuple[Fraction, ...]]

    def __post_init__(self) -> None:
        if not self.worlds or len(set(self.worlds)) != len(self.worlds):
            raise ValueError("worlds must be nonempty and unique")
        if not self.outcomes or len(set(self.outcomes)) != len(self.outcomes):
            raise ValueError("outcomes must be nonempty and unique")
        if set(self.laws) != set(self.worlds):
            raise ValueError("laws must cover exactly the worlds")
        for world in self.worlds:
            law = self.laws[world]
            if len(law) != len(self.outcomes):
                raise ValueError("law length must match outcomes")
            validate_distribution(law)

    def to_data(self) -> dict[str, object]:
        return {
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
    ) -> "FiniteClassificationProblem":
        worlds = data.get("worlds")
        outcomes = data.get("outcomes")
        laws_data = data.get("laws")
        if (
            not isinstance(worlds, list)
            or not all(isinstance(value, str) for value in worlds)
            or not isinstance(outcomes, list)
            or not all(isinstance(value, str) for value in outcomes)
            or not isinstance(laws_data, Mapping)
        ):
            raise ValueError("malformed classification problem")
        laws: dict[str, tuple[Fraction, ...]] = {}
        for world in worlds:
            raw = laws_data.get(world)
            if not isinstance(raw, list):
                raise ValueError("malformed law")
            laws[world] = tuple(parse_fraction(value) for value in raw)
        return cls(tuple(worlds), tuple(outcomes), laws)


def make_mary_symmetric_channel(
    classes: int, error_probability: Fraction
) -> FiniteClassificationProblem:
    if classes < 2:
        raise ValueError("at least two classes are required")
    if not (0 <= error_probability <= Fraction(classes - 1, classes)):
        raise ValueError("the declared label must remain Bayes-optimal")
    worlds = tuple(f"class_{index}" for index in range(classes))
    outcomes = worlds
    wrong = error_probability / (classes - 1)
    laws = {
        world: tuple(
            1 - error_probability if index == world_index else wrong
            for index in range(classes)
        )
        for world_index, world in enumerate(worlds)
    }
    return FiniteClassificationProblem(worlds, outcomes, laws)


def uniform_bayes_classifier(
    problem: FiniteClassificationProblem,
    subset: Sequence[str] | None = None,
) -> dict[str, object]:
    selected = tuple(problem.worlds if subset is None else subset)
    if len(selected) < 2 or not set(selected) <= set(problem.worlds):
        raise ValueError("a valid subset with at least two worlds is required")
    prior = Fraction(1, len(selected))
    decoder: list[str] = []
    success = Fraction(0)
    for outcome_index in range(len(problem.outcomes)):
        best_world = min(
            selected,
            key=lambda world: (
                -problem.laws[world][outcome_index], world
            ),
        )
        decoder.append(best_world)
        success += prior * problem.laws[best_world][outcome_index]
    error = 1 - success
    risks = {
        world: 1
        - sum(
            (
                problem.laws[world][outcome_index]
                for outcome_index, decision in enumerate(decoder)
                if decision == world
            ),
            Fraction(0),
        )
        for world in selected
    }
    maximum_risk = max(risks.values())
    return {
        "subset": list(selected),
        "uniform_prior": fraction_data(prior),
        "decoder": {
            problem.outcomes[index]: decision
            for index, decision in enumerate(decoder)
        },
        "uniform_bayes_error": fraction_data(error),
        "world_risks": {
            world: fraction_data(risks[world]) for world in selected
        },
        "candidate_maximum_risk": fraction_data(maximum_risk),
        "matched_exact_minimax": error == maximum_risk,
        "exact_minimax_value": fraction_data(error)
        if error == maximum_risk
        else None,
    }


def build_classification_certificate(
    problem: FiniteClassificationProblem, case_name: str
) -> dict[str, object]:
    payload = {
        "schema": "inference-power-compiler/multiway-classification/1",
        "case": case_name,
        "problem": problem.to_data(),
        "result": uniform_bayes_classifier(problem),
    }
    return {"payload": payload, "sha256": digest_payload(payload)}


def verify_classification_certificate(
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
        problem = FiniteClassificationProblem.from_data(problem_data)
        rebuilt = build_classification_certificate(problem, case_name)
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    return [] if canonical_json(rebuilt["payload"]) == canonical_json(payload) else ["semantic-replay"]


def strongest_packing_lower_bound(
    problem: FiniteEstimationProblem,
    *,
    max_subset_size: int = 8,
    max_packings: int = 10000,
) -> dict[str, object]:
    if max_subset_size < 2:
        raise ValueError("max_subset_size must be at least two")
    classification = FiniteClassificationProblem(
        problem.worlds, problem.outcomes, problem.laws
    )
    packings: list[dict[str, object]] = []
    examined = 0
    best: tuple[Fraction, int, tuple[str, ...]] | None = None
    best_entry: dict[str, object] | None = None
    maximum_size = min(max_subset_size, len(problem.worlds))
    for size in range(2, maximum_size + 1):
        for subset in combinations(problem.worlds, size):
            examined += 1
            if examined > max_packings:
                raise RuntimeError("packing enumeration exceeded resource bound")
            separations = [
                squared_distance(
                    problem.targets[left], problem.targets[right]
                )
                for left_index, left in enumerate(subset)
                for right in subset[left_index + 1 :]
            ]
            minimum_separation_sq = min(separations)
            testing = uniform_bayes_classifier(classification, subset)
            testing_error = Fraction(*testing["uniform_bayes_error"])
            radius_sq = minimum_separation_sq / 4
            lower_bound = radius_sq * testing_error
            entry = {
                "subset": list(subset),
                "size": size,
                "minimum_squared_target_separation": fraction_data(
                    minimum_separation_sq
                ),
                "packing_radius_squared": fraction_data(radius_sq),
                "optimal_uniform_testing_error": fraction_data(
                    testing_error
                ),
                "estimation_lower_bound": fraction_data(lower_bound),
                "testing_decoder": testing["decoder"],
            }
            packings.append(entry)
            candidate = (lower_bound, size, subset)
            if best is None or candidate > best:
                best = candidate
                best_entry = entry
    if best_entry is None:
        raise ValueError("no packing was generated")
    return {
        "method": "exact finite packing-to-testing reduction",
        "loss": "squared Euclidean",
        "packings_examined": examined,
        "resource_limits": {
            "max_subset_size": max_subset_size,
            "max_packings": max_packings,
        },
        "strongest_witness": best_entry,
        "strongest_lower_bound": best_entry[
            "estimation_lower_bound"
        ],
        "all_packings": packings,
    }


def build_packing_certificate(
    problem: FiniteEstimationProblem,
    case_name: str,
    *,
    max_subset_size: int = 8,
    max_packings: int = 10000,
) -> dict[str, object]:
    payload = {
        "schema": "inference-power-compiler/packing-lower-bound/1",
        "case": case_name,
        "problem": problem.to_data(),
        "result": strongest_packing_lower_bound(
            problem,
            max_subset_size=max_subset_size,
            max_packings=max_packings,
        ),
    }
    return {"payload": payload, "sha256": digest_payload(payload)}


def verify_packing_certificate(
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
        result = payload.get("result")
        if (
            not isinstance(problem_data, Mapping)
            or not isinstance(case_name, str)
            or not isinstance(result, Mapping)
        ):
            raise ValueError("malformed payload")
        limits = result.get("resource_limits")
        if not isinstance(limits, Mapping):
            raise ValueError("missing resource limits")
        max_subset_size = limits.get("max_subset_size")
        max_packings = limits.get("max_packings")
        if not isinstance(max_subset_size, int) or not isinstance(
            max_packings, int
        ):
            raise ValueError("malformed resource limits")
        problem = FiniteEstimationProblem.from_data(problem_data)
        rebuilt = build_packing_certificate(
            problem,
            case_name,
            max_subset_size=max_subset_size,
            max_packings=max_packings,
        )
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    return [] if canonical_json(rebuilt["payload"]) == canonical_json(payload) else ["semantic-replay"]
