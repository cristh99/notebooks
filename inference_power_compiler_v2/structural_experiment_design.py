from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
from typing import Mapping, Sequence

from logic_power_v10 import (
    ActiveDiscoveryProblem,
    Experiment,
    build_certificate as build_logic_certificate,
    verify_certificate as verify_logic_certificate,
)
from logic_power_v10.certificate import canonical_json


def _fraction_data(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def _fraction(value: object) -> Fraction:
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


def _validate_distribution(probabilities: Sequence[Fraction]) -> None:
    if not probabilities:
        raise ValueError("a probability law must be nonempty")
    if any(probability < 0 for probability in probabilities):
        raise ValueError("probabilities must be nonnegative")
    if sum(probabilities, Fraction(0)) != 1:
        raise ValueError("probabilities must sum exactly to one")


def _law_signature(law: Sequence[Fraction]) -> str:
    return "|".join(
        f"{probability.numerator}/{probability.denominator}"
        for probability in law
    )


@dataclass(frozen=True)
class RationalExperiment:
    """One exact finite statistical experiment.

    ``laws[theta]`` is the full observable distribution under hidden world
    ``theta``. The structural compiler treats that distribution itself as the
    oracle observation. It therefore solves experiment selection for
    identifiability, not finite-sample estimation.
    """

    name: str
    cost: Fraction
    outcomes: tuple[str, ...]
    laws: Mapping[str, tuple[Fraction, ...]]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("experiment name must be nonempty")
        if self.cost <= 0:
            raise ValueError("experiment cost must be positive")
        if not self.outcomes:
            raise ValueError("experiment outcome space must be nonempty")
        if len(set(self.outcomes)) != len(self.outcomes):
            raise ValueError("experiment outcomes must be unique")
        if not self.laws:
            raise ValueError("experiment laws must be supplied")
        for law in self.laws.values():
            if len(law) != len(self.outcomes):
                raise ValueError("every law must match the outcome space")
            _validate_distribution(law)

    def signature(self, theta: str) -> str:
        return _law_signature(self.laws[theta])

    def to_data(self) -> dict[str, object]:
        return {
            "name": self.name,
            "cost": _fraction_data(self.cost),
            "outcomes": list(self.outcomes),
            "laws": {
                theta: [_fraction_data(value) for value in self.laws[theta]]
                for theta in sorted(self.laws)
            },
        }

    @classmethod
    def from_data(cls, data: Mapping[str, object]) -> "RationalExperiment":
        name = data.get("name")
        outcomes = data.get("outcomes")
        laws_data = data.get("laws")
        if (
            not isinstance(name, str)
            or not isinstance(outcomes, list)
            or not all(isinstance(outcome, str) for outcome in outcomes)
            or not isinstance(laws_data, Mapping)
        ):
            raise ValueError("malformed experiment")
        laws: dict[str, tuple[Fraction, ...]] = {}
        for theta, raw_law in laws_data.items():
            if not isinstance(theta, str) or not isinstance(raw_law, list):
                raise ValueError("malformed experiment law")
            laws[theta] = tuple(_fraction(value) for value in raw_law)
        return cls(
            name=name,
            cost=_fraction(data.get("cost")),
            outcomes=tuple(outcomes),
            laws=laws,
        )


@dataclass(frozen=True)
class StructuralDesignProblem:
    """Finite structural-identifiability and experiment-selection problem."""

    parameters: tuple[str, ...]
    target: Mapping[str, bool]
    experiments: tuple[RationalExperiment, ...]
    prior: Mapping[str, Fraction]

    def __post_init__(self) -> None:
        if not self.parameters:
            raise ValueError("at least one parameter/world is required")
        if len(set(self.parameters)) != len(self.parameters):
            raise ValueError("parameter identifiers must be unique")
        parameter_set = set(self.parameters)
        if set(self.target) != parameter_set:
            raise ValueError("target must cover exactly the parameters")
        if set(self.prior) != parameter_set:
            raise ValueError("prior must cover exactly the parameters")
        if any(weight <= 0 for weight in self.prior.values()):
            raise ValueError("planning-prior weights must be positive")
        if sum(self.prior.values(), Fraction(0)) <= 0:
            raise ValueError("planning prior must have positive mass")
        names = [experiment.name for experiment in self.experiments]
        if len(set(names)) != len(names):
            raise ValueError("experiment names must be unique")
        for experiment in self.experiments:
            if set(experiment.laws) != parameter_set:
                raise ValueError(
                    f"experiment {experiment.name} must define every world"
                )

    def to_logic_problem(self) -> ActiveDiscoveryProblem:
        experiments = tuple(
            Experiment(
                name=experiment.name,
                cost=experiment.cost,
                observations={
                    theta: experiment.signature(theta)
                    for theta in self.parameters
                },
            )
            for experiment in self.experiments
        )
        return ActiveDiscoveryProblem(
            hypotheses=self.parameters,
            property_values=self.target,
            experiments=experiments,
            prior=self.prior,
        )

    def to_data(self) -> dict[str, object]:
        total = sum(self.prior.values(), Fraction(0))
        return {
            "parameters": list(self.parameters),
            "target": {
                theta: bool(self.target[theta])
                for theta in sorted(self.parameters)
            },
            "prior": {
                theta: _fraction_data(self.prior[theta] / total)
                for theta in sorted(self.parameters)
            },
            "experiments": [
                experiment.to_data() for experiment in self.experiments
            ],
        }

    @classmethod
    def from_data(cls, data: Mapping[str, object]) -> "StructuralDesignProblem":
        parameters = data.get("parameters")
        target_data = data.get("target")
        prior_data = data.get("prior")
        experiments_data = data.get("experiments")
        if (
            not isinstance(parameters, list)
            or not all(isinstance(theta, str) for theta in parameters)
            or not isinstance(target_data, Mapping)
            or not isinstance(prior_data, Mapping)
            or not isinstance(experiments_data, list)
        ):
            raise ValueError("malformed structural-design problem")
        target = {
            str(theta): bool(value) for theta, value in target_data.items()
        }
        prior = {
            str(theta): _fraction(value)
            for theta, value in prior_data.items()
        }
        experiments = tuple(
            RationalExperiment.from_data(item)
            for item in experiments_data
            if isinstance(item, Mapping)
        )
        if len(experiments) != len(experiments_data):
            raise ValueError("malformed experiment list")
        return cls(
            parameters=tuple(parameters),
            target=target,
            experiments=experiments,
            prior=prior,
        )


def build_structural_design_certificate(
    problem: StructuralDesignProblem,
    case_name: str,
) -> dict[str, object]:
    """Compile exact-law experiment selection through Logic Power v10."""

    logic_certificate = build_logic_certificate(
        problem.to_logic_problem(), case_name
    )
    logic_errors = verify_logic_certificate(logic_certificate)
    if logic_errors:
        raise AssertionError(
            f"Logic Power v10 certificate failed replay: {logic_errors}"
        )
    analysis = logic_certificate["payload"]["analysis"]
    obstruction = analysis["obstruction"]
    status = "IMPOSSIBLE" if obstruction is not None else "SOLVED"
    payload = {
        "schema": (
            "inference-power-compiler/"
            "structural-experiment-design-certificate/1"
        ),
        "case": case_name,
        "semantics": (
            "Each candidate experiment returns its exact observable law. "
            "The certificate solves structural identifiability and oracle "
            "experiment selection, not finite-sample estimation."
        ),
        "problem": problem.to_data(),
        "result": {
            "status": status,
            "fixed_basis": analysis["fixed_basis"],
            "fixed_basis_cost": analysis["fixed_basis_cost"],
            "obstruction": obstruction,
            "optimal_policy": analysis["policy"],
        },
        "logic_power_v10": {
            "certificate_sha256": logic_certificate["sha256"],
            "certificate": logic_certificate,
        },
    }
    return {
        "payload": payload,
        "sha256": sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    }


def verify_structural_design_certificate(
    certificate: Mapping[str, object],
) -> list[str]:
    """Fail-closed semantic replay of a structural-design certificate."""

    payload = certificate.get("payload")
    certificate_hash = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(
        certificate_hash, str
    ):
        return ["certificate-shape"]
    if (
        sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        != certificate_hash
    ):
        return ["payload-hash"]
    try:
        problem_data = payload["problem"]
        case_name = payload["case"]
        if not isinstance(problem_data, Mapping) or not isinstance(
            case_name, str
        ):
            raise ValueError("malformed certificate payload")
        problem = StructuralDesignProblem.from_data(problem_data)
        rebuilt = build_structural_design_certificate(problem, case_name)
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    if canonical_json(rebuilt["payload"]) != canonical_json(payload):
        return ["semantic-replay"]
    return []


def bernoulli(success_probability: Fraction) -> tuple[Fraction, Fraction]:
    if success_probability < 0 or success_probability > 1:
        raise ValueError("Bernoulli probability must lie in [0,1]")
    return (1 - success_probability, success_probability)


def causal_intervention_problem(
    *, observational_only: bool = False
) -> StructuralDesignProblem:
    """Two observationally equivalent causal worlds separated by intervention."""

    parameters = ("confounded_no_effect", "direct_positive_effect")
    observe = RationalExperiment(
        name="observe_joint_proxy",
        cost=Fraction(1),
        outcomes=("0", "1"),
        laws={
            "confounded_no_effect": bernoulli(Fraction(1, 2)),
            "direct_positive_effect": bernoulli(Fraction(1, 2)),
        },
    )
    do_zero = RationalExperiment(
        name="intervene_A_0",
        cost=Fraction(3),
        outcomes=("0", "1"),
        laws={
            "confounded_no_effect": bernoulli(Fraction(1, 2)),
            "direct_positive_effect": bernoulli(Fraction(0)),
        },
    )
    do_one = RationalExperiment(
        name="intervene_A_1",
        cost=Fraction(3),
        outcomes=("0", "1"),
        laws={
            "confounded_no_effect": bernoulli(Fraction(1, 2)),
            "direct_positive_effect": bernoulli(Fraction(1)),
        },
    )
    experiments = (observe,) if observational_only else (
        observe,
        do_zero,
        do_one,
    )
    return StructuralDesignProblem(
        parameters=parameters,
        target={
            "confounded_no_effect": False,
            "direct_positive_effect": True,
        },
        experiments=experiments,
        prior={
            "confounded_no_effect": Fraction(1, 2),
            "direct_positive_effect": Fraction(1, 2),
        },
    )


def adaptive_branch_problem() -> StructuralDesignProblem:
    """A small exact-law design where adaptivity beats every fixed basis."""

    parameters = ("h0", "h1", "h2", "h3")
    target = {"h0": False, "h1": False, "h2": True, "h3": True}
    screen = RationalExperiment(
        name="screen_branch",
        cost=Fraction(1),
        outcomes=("0", "1"),
        laws={
            "h0": bernoulli(Fraction(0)),
            "h2": bernoulli(Fraction(0)),
            "h1": bernoulli(Fraction(1)),
            "h3": bernoulli(Fraction(1)),
        },
    )
    left = RationalExperiment(
        name="resolve_left",
        cost=Fraction(4),
        outcomes=("0", "1"),
        laws={
            "h0": bernoulli(Fraction(0)),
            "h2": bernoulli(Fraction(1)),
            "h1": bernoulli(Fraction(1, 2)),
            "h3": bernoulli(Fraction(1, 2)),
        },
    )
    right = RationalExperiment(
        name="resolve_right",
        cost=Fraction(7),
        outcomes=("0", "1"),
        laws={
            "h1": bernoulli(Fraction(0)),
            "h3": bernoulli(Fraction(1)),
            "h0": bernoulli(Fraction(1, 2)),
            "h2": bernoulli(Fraction(1, 2)),
        },
    )
    return StructuralDesignProblem(
        parameters=parameters,
        target=target,
        experiments=(screen, left, right),
        prior={
            "h0": Fraction(9, 20),
            "h2": Fraction(9, 20),
            "h1": Fraction(1, 20),
            "h3": Fraction(1, 20),
        },
    )
