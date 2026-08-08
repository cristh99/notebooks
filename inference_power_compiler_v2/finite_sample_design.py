from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from itertools import combinations, product
from typing import Mapping, Sequence

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
        raise ValueError("probability law must be nonempty")
    if any(value < 0 for value in probabilities):
        raise ValueError("probabilities must be nonnegative")
    if sum(probabilities, Fraction(0)) != 1:
        raise ValueError("probabilities must sum exactly to one")


def _digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SamplingExperiment:
    name: str
    cost: Fraction
    outcomes: tuple[str, ...]
    laws: Mapping[str, tuple[Fraction, ...]]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("experiment name must be nonempty")
        if self.cost < 0:
            raise ValueError("experiment cost must be nonnegative")
        if not self.outcomes or len(set(self.outcomes)) != len(self.outcomes):
            raise ValueError("experiment outcomes must be nonempty and unique")
        if not self.laws:
            raise ValueError("experiment laws are required")
        for law in self.laws.values():
            if len(law) != len(self.outcomes):
                raise ValueError("law length must match outcomes")
            _validate_distribution(law)

    def to_data(self) -> dict[str, object]:
        return {
            "name": self.name,
            "cost": _fraction_data(self.cost),
            "outcomes": list(self.outcomes),
            "laws": {
                world: [_fraction_data(value) for value in self.laws[world]]
                for world in sorted(self.laws)
            },
        }

    @classmethod
    def from_data(cls, data: Mapping[str, object]) -> "SamplingExperiment":
        name = data.get("name")
        outcomes = data.get("outcomes")
        laws_data = data.get("laws")
        if (
            not isinstance(name, str)
            or not isinstance(outcomes, list)
            or not all(isinstance(outcome, str) for outcome in outcomes)
            or not isinstance(laws_data, Mapping)
        ):
            raise ValueError("malformed sampling experiment")
        laws: dict[str, tuple[Fraction, ...]] = {}
        for world, raw_law in laws_data.items():
            if not isinstance(world, str) or not isinstance(raw_law, list):
                raise ValueError("malformed sampling law")
            laws[world] = tuple(_fraction(value) for value in raw_law)
        return cls(
            name=name,
            cost=_fraction(data.get("cost")),
            outcomes=tuple(outcomes),
            laws=laws,
        )


@dataclass(frozen=True)
class FiniteSampleDesignProblem:
    worlds: tuple[str, ...]
    actions: tuple[str, ...]
    loss: Mapping[tuple[str, str], Fraction]
    experiments: tuple[SamplingExperiment, ...]
    horizon: int

    def __post_init__(self) -> None:
        if not self.worlds or len(set(self.worlds)) != len(self.worlds):
            raise ValueError("worlds must be nonempty and unique")
        if not self.actions or len(set(self.actions)) != len(self.actions):
            raise ValueError("actions must be nonempty and unique")
        if self.horizon < 0:
            raise ValueError("horizon must be nonnegative")
        expected_loss_keys = {
            (world, action)
            for world in self.worlds
            for action in self.actions
        }
        if set(self.loss) != expected_loss_keys:
            raise ValueError("loss must cover every world-action pair")
        if any(value < 0 for value in self.loss.values()):
            raise ValueError("losses must be nonnegative")
        names = [experiment.name for experiment in self.experiments]
        if len(set(names)) != len(names):
            raise ValueError("experiment names must be unique")
        for experiment in self.experiments:
            if set(experiment.laws) != set(self.worlds):
                raise ValueError(
                    f"experiment {experiment.name} must cover all worlds"
                )

    def to_data(self) -> dict[str, object]:
        return {
            "worlds": list(self.worlds),
            "actions": list(self.actions),
            "loss": {
                f"{world}|{action}": _fraction_data(
                    self.loss[(world, action)]
                )
                for world in sorted(self.worlds)
                for action in sorted(self.actions)
            },
            "experiments": [
                experiment.to_data() for experiment in self.experiments
            ],
            "horizon": self.horizon,
        }

    @classmethod
    def from_data(
        cls, data: Mapping[str, object]
    ) -> "FiniteSampleDesignProblem":
        worlds = data.get("worlds")
        actions = data.get("actions")
        loss_data = data.get("loss")
        experiments_data = data.get("experiments")
        horizon = data.get("horizon")
        if (
            not isinstance(worlds, list)
            or not all(isinstance(world, str) for world in worlds)
            or not isinstance(actions, list)
            or not all(isinstance(action, str) for action in actions)
            or not isinstance(loss_data, Mapping)
            or not isinstance(experiments_data, list)
            or not isinstance(horizon, int)
        ):
            raise ValueError("malformed finite-sample problem")
        loss: dict[tuple[str, str], Fraction] = {}
        for key, value in loss_data.items():
            if not isinstance(key, str) or "|" not in key:
                raise ValueError("malformed loss key")
            world, action = key.split("|", 1)
            loss[(world, action)] = _fraction(value)
        experiments = tuple(
            SamplingExperiment.from_data(item)
            for item in experiments_data
            if isinstance(item, Mapping)
        )
        if len(experiments) != len(experiments_data):
            raise ValueError("malformed experiment list")
        return cls(
            worlds=tuple(worlds),
            actions=tuple(actions),
            loss=loss,
            experiments=experiments,
            horizon=horizon,
        )


@dataclass(frozen=True)
class DeterministicPolicy:
    risks: tuple[Fraction, ...]
    tree: Mapping[str, object]
    digest: str

    @classmethod
    def build(
        cls,
        risks: Sequence[Fraction],
        tree: Mapping[str, object],
    ) -> "DeterministicPolicy":
        payload = {
            "risks": [_fraction_data(value) for value in risks],
            "tree": tree,
        }
        return cls(
            risks=tuple(risks),
            tree=tree,
            digest=_digest(payload),
        )

    def to_data(self) -> dict[str, object]:
        return {
            "risks": [_fraction_data(value) for value in self.risks],
            "tree": self.tree,
            "sha256": self.digest,
        }


def _prune_policies(
    policies: Sequence[DeterministicPolicy],
) -> tuple[DeterministicPolicy, ...]:
    by_risk: dict[tuple[Fraction, ...], DeterministicPolicy] = {}
    for policy in policies:
        incumbent = by_risk.get(policy.risks)
        if incumbent is None or policy.digest < incumbent.digest:
            by_risk[policy.risks] = policy
    unique = list(by_risk.values())
    keep: list[DeterministicPolicy] = []
    for index, policy in enumerate(unique):
        dominated = False
        for other_index, other in enumerate(unique):
            if index == other_index:
                continue
            if all(
                other.risks[i] <= policy.risks[i]
                for i in range(len(policy.risks))
            ) and any(
                other.risks[i] < policy.risks[i]
                for i in range(len(policy.risks))
            ):
                dominated = True
                break
        if not dominated:
            keep.append(policy)
    return tuple(
        sorted(
            keep,
            key=lambda policy: (
                policy.risks,
                canonical_json(policy.tree),
                policy.digest,
            ),
        )
    )


def enumerate_policy_frontier(
    problem: FiniteSampleDesignProblem,
    *,
    max_raw_policies: int = 100_000,
    max_frontier_policies: int = 1_000,
) -> tuple[tuple[DeterministicPolicy, ...], tuple[int, ...]]:
    """Enumerate and Pareto-prune deterministic policies up to the horizon."""

    base = tuple(
        DeterministicPolicy.build(
            [problem.loss[(world, action)] for world in problem.worlds],
            {"kind": "stop", "action": action},
        )
        for action in problem.actions
    )

    @lru_cache(maxsize=None)
    def frontier(remaining: int) -> tuple[DeterministicPolicy, ...]:
        if remaining == 0:
            return _prune_policies(base)
        previous = frontier(remaining - 1)
        generated: list[DeterministicPolicy] = list(base)
        for experiment in problem.experiments:
            combinations_count = len(previous) ** len(
                experiment.outcomes
            )
            if len(generated) + combinations_count > max_raw_policies:
                raise RuntimeError(
                    "raw policy enumeration exceeds declared resource limit"
                )
            for children in product(
                previous, repeat=len(experiment.outcomes)
            ):
                risks: list[Fraction] = []
                for world_index, world in enumerate(problem.worlds):
                    risk = experiment.cost + sum(
                        (
                            experiment.laws[world][outcome_index]
                            * children[outcome_index].risks[world_index]
                            for outcome_index in range(
                                len(experiment.outcomes)
                            )
                        ),
                        Fraction(0),
                    )
                    risks.append(risk)
                tree = {
                    "kind": "experiment",
                    "experiment": experiment.name,
                    "cost": _fraction_data(experiment.cost),
                    "children": {
                        experiment.outcomes[outcome_index]: children[
                            outcome_index
                        ].tree
                        for outcome_index in range(
                            len(experiment.outcomes)
                        )
                    },
                }
                generated.append(
                    DeterministicPolicy.build(risks, tree)
                )
        result = _prune_policies(generated)
        if len(result) > max_frontier_policies:
            raise RuntimeError(
                "Pareto frontier exceeds declared resource limit"
            )
        return result

    frontiers = tuple(
        len(frontier(remaining))
        for remaining in range(problem.horizon + 1)
    )
    return frontier(problem.horizon), frontiers


def _solve_square(
    matrix: Sequence[Sequence[Fraction]],
    rhs: Sequence[Fraction],
) -> list[Fraction] | None:
    n = len(matrix)
    if n == 0 or len(rhs) != n or any(len(row) != n for row in matrix):
        raise ValueError("a nonempty square system is required")
    augmented = [
        [Fraction(value) for value in matrix[index]]
        + [Fraction(rhs[index])]
        for index in range(n)
    ]
    pivot_row = 0
    for column in range(n):
        pivot = next(
            (
                row
                for row in range(pivot_row, n)
                if augmented[row][column] != 0
            ),
            None,
        )
        if pivot is None:
            return None
        augmented[pivot_row], augmented[pivot] = (
            augmented[pivot],
            augmented[pivot_row],
        )
        pivot_value = augmented[pivot_row][column]
        augmented[pivot_row] = [
            value / pivot_value for value in augmented[pivot_row]
        ]
        for row in range(n):
            if row == pivot_row or augmented[row][column] == 0:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index]
                - factor * augmented[pivot_row][index]
                for index in range(n + 1)
            ]
        pivot_row += 1
    return [augmented[index][-1] for index in range(n)]


def _solve_primal(
    risk: Sequence[Sequence[Fraction]],
) -> tuple[Fraction, tuple[Fraction, ...], int]:
    world_count = len(risk)
    policy_count = len(risk[0])
    variable_count = policy_count + 1
    active_rows: list[tuple[tuple[Fraction, ...], Fraction]] = []

    for policy_index in range(policy_count):
        row = [Fraction(0)] * variable_count
        row[policy_index] = Fraction(1)
        active_rows.append((tuple(row), Fraction(0)))
    for world_index in range(world_count):
        active_rows.append(
            (
                tuple(risk[world_index]) + (Fraction(-1),),
                Fraction(0),
            )
        )

    best: tuple[Fraction, tuple[Fraction, ...]] | None = None
    examined = 0
    for active in combinations(
        range(len(active_rows)), policy_count
    ):
        examined += 1
        matrix = [
            [Fraction(1)] * policy_count + [Fraction(0)]
        ]
        rhs = [Fraction(1)]
        for row_index in active:
            matrix.append(list(active_rows[row_index][0]))
            rhs.append(active_rows[row_index][1])
        solution = _solve_square(matrix, rhs)
        if solution is None:
            continue
        mixture = tuple(solution[:policy_count])
        value = solution[-1]
        if any(weight < 0 for weight in mixture):
            continue
        world_risks = tuple(
            sum(
                (
                    risk[world][policy] * mixture[policy]
                    for policy in range(policy_count)
                ),
                Fraction(0),
            )
            for world in range(world_count)
        )
        if any(current > value for current in world_risks):
            continue
        candidate = (value, mixture)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise RuntimeError("no primal minimax certificate found")
    return best[0], best[1], examined


def _solve_dual(
    risk: Sequence[Sequence[Fraction]],
) -> tuple[Fraction, tuple[Fraction, ...], int]:
    world_count = len(risk)
    policy_count = len(risk[0])
    variable_count = world_count + 1
    active_rows: list[tuple[tuple[Fraction, ...], Fraction]] = []

    for world_index in range(world_count):
        row = [Fraction(0)] * variable_count
        row[world_index] = Fraction(1)
        active_rows.append((tuple(row), Fraction(0)))
    for policy_index in range(policy_count):
        active_rows.append(
            (
                tuple(
                    risk[world][policy_index]
                    for world in range(world_count)
                )
                + (Fraction(-1),),
                Fraction(0),
            )
        )

    best: tuple[Fraction, tuple[Fraction, ...]] | None = None
    examined = 0
    for active in combinations(
        range(len(active_rows)), world_count
    ):
        examined += 1
        matrix = [
            [Fraction(1)] * world_count + [Fraction(0)]
        ]
        rhs = [Fraction(1)]
        for row_index in active:
            matrix.append(list(active_rows[row_index][0]))
            rhs.append(active_rows[row_index][1])
        solution = _solve_square(matrix, rhs)
        if solution is None:
            continue
        prior = tuple(solution[:world_count])
        value = solution[-1]
        if any(weight < 0 for weight in prior):
            continue
        policy_values = tuple(
            sum(
                (
                    prior[world] * risk[world][policy]
                    for world in range(world_count)
                ),
                Fraction(0),
            )
            for policy in range(policy_count)
        )
        if any(current < value for current in policy_values):
            continue
        candidate = (value, prior)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        raise RuntimeError("no dual minimax certificate found")
    return best[0], best[1], examined


def solve_finite_sample_minimax(
    problem: FiniteSampleDesignProblem,
) -> dict[str, object]:
    policies, frontier_sizes = enumerate_policy_frontier(problem)
    risk = tuple(
        tuple(
            policy.risks[world_index] for policy in policies
        )
        for world_index in range(len(problem.worlds))
    )
    primal_value, mixture, primal_examined = _solve_primal(risk)
    dual_value, prior, dual_examined = _solve_dual(risk)
    if primal_value != dual_value:
        raise AssertionError(
            f"primal-dual gap: {primal_value} != {dual_value}"
        )

    world_risks = tuple(
        sum(
            (
                mixture[policy_index]
                * policies[policy_index].risks[world_index]
                for policy_index in range(len(policies))
            ),
            Fraction(0),
        )
        for world_index in range(len(problem.worlds))
    )
    policy_values = tuple(
        sum(
            (
                prior[world_index]
                * policy.risks[world_index]
                for world_index in range(len(problem.worlds))
            ),
            Fraction(0),
        )
        for policy in policies
    )
    if max(world_risks) != primal_value:
        raise AssertionError("primal mixture does not attain claimed value")
    if min(policy_values) != dual_value:
        raise AssertionError("dual prior does not attain claimed lower bound")

    support = [
        {
            "policy_index": index,
            "policy_sha256": policies[index].digest,
            "weight": _fraction_data(weight),
            "risks": [
                _fraction_data(value) for value in policies[index].risks
            ],
            "tree": policies[index].tree,
        }
        for index, weight in enumerate(mixture)
        if weight > 0
    ]
    return {
        "value": _fraction_data(primal_value),
        "frontier_sizes_by_horizon": list(frontier_sizes),
        "policy_count": len(policies),
        "policies": [policy.to_data() for policy in policies],
        "randomized_policy_support": support,
        "world_risks": [
            _fraction_data(value) for value in world_risks
        ],
        "least_favorable_prior": {
            problem.worlds[index]: _fraction_data(weight)
            for index, weight in enumerate(prior)
        },
        "dual_policy_values": [
            _fraction_data(value) for value in policy_values
        ],
        "primal_vertices_examined": primal_examined,
        "dual_vertices_examined": dual_examined,
    }


def build_finite_sample_certificate(
    problem: FiniteSampleDesignProblem,
    case_name: str,
) -> dict[str, object]:
    solution = solve_finite_sample_minimax(problem)
    payload = {
        "schema": (
            "inference-power-compiler/"
            "finite-sample-minimax-design-certificate/1"
        ),
        "case": case_name,
        "problem": problem.to_data(),
        "solution": solution,
    }
    return {"payload": payload, "sha256": _digest(payload)}


def verify_finite_sample_certificate(
    certificate: Mapping[str, object],
) -> list[str]:
    payload = certificate.get("payload")
    certificate_hash = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(
        certificate_hash, str
    ):
        return ["certificate-shape"]
    if _digest(payload) != certificate_hash:
        return ["payload-hash"]
    try:
        problem_data = payload["problem"]
        case_name = payload["case"]
        if not isinstance(problem_data, Mapping) or not isinstance(
            case_name, str
        ):
            raise ValueError("malformed payload")
        problem = FiniteSampleDesignProblem.from_data(problem_data)
        rebuilt = build_finite_sample_certificate(problem, case_name)
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    if canonical_json(rebuilt["payload"]) != canonical_json(payload):
        return ["semantic-replay"]
    return []


def causal_sampling_problem(
    *, observational_only: bool = False
) -> FiniteSampleDesignProblem:
    worlds = ("confounded_no_effect", "direct_positive_effect")
    actions = ("declare_no_effect", "declare_positive_effect")
    loss = {
        (world, action): Fraction(
            int(
                (world == "direct_positive_effect")
                != (action == "declare_positive_effect")
            )
        )
        for world in worlds
        for action in actions
    }
    observe = SamplingExperiment(
        name="observe_proxy",
        cost=Fraction(1, 100),
        outcomes=("0", "1"),
        laws={
            "confounded_no_effect": (Fraction(1, 2), Fraction(1, 2)),
            "direct_positive_effect": (
                Fraction(1, 2),
                Fraction(1, 2),
            ),
        },
    )
    intervene = SamplingExperiment(
        name="intervene_A_1",
        cost=Fraction(1, 20),
        outcomes=("0", "1"),
        laws={
            "confounded_no_effect": (Fraction(1, 2), Fraction(1, 2)),
            "direct_positive_effect": (Fraction(0), Fraction(1)),
        },
    )
    experiments = (observe,) if observational_only else (
        observe,
        intervene,
    )
    return FiniteSampleDesignProblem(
        worlds=worlds,
        actions=actions,
        loss=loss,
        experiments=experiments,
        horizon=2,
    )
