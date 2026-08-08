from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent
WORLDS = ("M0_U0", "M0_U1", "M1_U0", "M1_U1")
TARGET = {
    "M0_U0": Fraction(1, 4),
    "M0_U1": Fraction(1, 2),
    "M1_U0": Fraction(1, 2),
    "M1_U1": Fraction(3, 4),
}
PRIOR = {world: Fraction(1, 4) for world in WORLDS}
SNAPSHOT = "N=4|respondents=2|observed_positive=1|nonresponse=1|nonselected=1"
COST = {
    "recontact_nonresponse": Fraction(2),
    "link_nonselected": Fraction(3),
    "joint_population_validation": Fraction(7),
}
KERNEL: dict[str, dict[str, dict[str, Fraction]]] = {
    "recontact_nonresponse": {},
    "link_nonselected": {},
    "joint_population_validation": {},
}
for world in WORLDS:
    missing, unselected = int(world[1]), int(world[4])
    success = Fraction(7, 8) if missing == 0 else Fraction(3, 4)
    KERNEL["recontact_nonresponse"][world] = {
        f"Y_missing={missing}": success,
        "FAIL": 1 - success,
    }
    KERNEL["link_nonselected"][world] = {
        f"Y_nonselected={unselected}": Fraction(1)
    }
    KERNEL["joint_population_validation"][world] = {
        f"Y_missing={missing}|Y_nonselected={unselected}": Fraction(1)
    }
PAID = tuple(sorted(COST))
BUDGETS = tuple(Fraction(value) for value in (0, 2, 3, 5, 7, 9))
Policy = tuple[object, ...]
Belief = tuple[tuple[str, Fraction], ...]


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def normalize(weights: Mapping[str, Fraction]) -> Belief:
    positive = {world: weight for world, weight in weights.items() if weight > 0}
    total = sum(positive.values(), Fraction(0))
    if total <= 0:
        raise ValueError("zero posterior mass")
    return tuple(sorted((world, weight / total) for world, weight in positive.items()))


def interval(belief: Belief) -> tuple[Fraction, Fraction]:
    values = [TARGET[world] for world, weight in belief if weight > 0]
    return min(values), max(values)


def predictive(belief: Belief, experiment: str) -> tuple[tuple[str, Fraction], ...]:
    law: dict[str, Fraction] = {}
    for world, posterior_probability in belief:
        for observation, likelihood in KERNEL[experiment][world].items():
            law[observation] = law.get(observation, Fraction(0)) + posterior_probability * likelihood
    return tuple(
        (observation, probability)
        for observation, probability in sorted(law.items())
        if probability > 0
    )


def posterior(belief: Belief, experiment: str, observation: str) -> Belief:
    return normalize(
        {
            world: probability * KERNEL[experiment][world].get(observation, Fraction(0))
            for world, probability in belief
        }
    )


def policy_data(policy: Policy) -> object:
    if policy[0] == "stop":
        return ["stop"]
    return [
        "ask",
        policy[1],
        [[observation, policy_data(child)] for observation, child in policy[2]],
    ]


@dataclass(frozen=True)
class Candidate:
    worst_width: Fraction
    expected_width: Fraction
    worst_cost: Fraction
    expected_cost: Fraction
    policy: Policy

    def metrics(self) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        return self.worst_width, self.expected_width, self.worst_cost, self.expected_cost

    def data(self) -> dict[str, object]:
        encoded = policy_data(self.policy)
        return {
            "worst_width": q(self.worst_width),
            "expected_width": q(self.expected_width),
            "worst_cost": q(self.worst_cost),
            "expected_cost": q(self.expected_cost),
            "policy": encoded,
            "policy_sha256": digest(encoded),
        }


def dominates(left: Candidate, right: Candidate) -> bool:
    a, b = left.metrics(), right.metrics()
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def pareto(candidates: Sequence[Candidate]) -> tuple[Candidate, ...]:
    by_metrics: dict[tuple[Fraction, ...], Candidate] = {}
    for candidate in candidates:
        key = candidate.metrics()
        incumbent = by_metrics.get(key)
        if incumbent is None or canonical(policy_data(candidate.policy)) < canonical(policy_data(incumbent.policy)):
            by_metrics[key] = candidate
    unique = tuple(by_metrics.values())
    frontier = [
        candidate
        for candidate in unique
        if not any(other is not candidate and dominates(other, candidate) for other in unique)
    ]
    return tuple(
        sorted(
            frontier,
            key=lambda item: (
                item.expected_width,
                item.worst_width,
                item.expected_cost,
                item.worst_cost,
                canonical(policy_data(item.policy)),
            ),
        )
    )


def frontier(budget: Fraction) -> tuple[Candidate, ...]:
    examined = 0

    @lru_cache(maxsize=None)
    def solve(belief: Belief, available: tuple[str, ...], remaining_budget: Fraction) -> tuple[Candidate, ...]:
        nonlocal examined
        lower, upper = interval(belief)
        width = upper - lower
        candidates = [Candidate(width, width, Fraction(0), Fraction(0), ("stop",))]
        for experiment in available:
            cost = COST[experiment]
            if cost > remaining_budget:
                continue
            law = predictive(belief, experiment)
            next_available = tuple(name for name in available if name != experiment)
            child_frontiers = tuple(
                solve(posterior(belief, experiment, observation), next_available, remaining_budget - cost)
                for observation, _probability in law
            )
            count = 1
            for child_frontier in child_frontiers:
                count *= len(child_frontier)
            examined += count
            if examined > 2_000_000:
                raise RuntimeError("finite policy enumeration limit exceeded")
            for children in product(*child_frontiers):
                candidates.append(
                    Candidate(
                        max(child.worst_width for child in children),
                        sum(
                            probability * child.expected_width
                            for (_observation, probability), child in zip(law, children)
                        ),
                        cost + max(child.worst_cost for child in children),
                        cost
                        + sum(
                            probability * child.expected_cost
                            for (_observation, probability), child in zip(law, children)
                        ),
                        (
                            "ask",
                            experiment,
                            tuple(
                                (observation, child.policy)
                                for (observation, _probability), child in zip(law, children)
                            ),
                        ),
                    )
                )
        return pareto(candidates)

    return solve(normalize(PRIOR), PAID, budget)


def replay(policy: Policy, belief: Belief, available: frozenset[str], budget: Fraction) -> Candidate:
    lower, upper = interval(belief)
    width = upper - lower
    if policy[0] == "stop":
        if policy != ("stop",):
            raise AssertionError("malformed stop")
        return Candidate(width, width, Fraction(0), Fraction(0), policy)
    if len(policy) != 3 or policy[0] != "ask" or not isinstance(policy[1], str):
        raise AssertionError("malformed policy")
    experiment = policy[1]
    if experiment not in available or COST[experiment] > budget:
        raise AssertionError("invalid experiment or budget")
    law = predictive(belief, experiment)
    children = policy[2]
    if not isinstance(children, tuple) or tuple(observation for observation, _child in children) != tuple(observation for observation, _probability in law):
        raise AssertionError("policy support mismatch")
    replayed = tuple(
        replay(
            child,
            posterior(belief, experiment, observation),
            available - {experiment},
            budget - COST[experiment],
        )
        for (observation, child), (_expected_observation, _probability) in zip(children, law)
    )
    return Candidate(
        max(child.worst_width for child in replayed),
        sum(probability * child.expected_width for (_observation, probability), child in zip(law, replayed)),
        COST[experiment] + max(child.worst_cost for child in replayed),
        COST[experiment]
        + sum(probability * child.expected_cost for (_observation, probability), child in zip(law, replayed)),
        policy,
    )


def best(frontier_value: Sequence[Candidate]) -> Candidate:
    return min(
        frontier_value,
        key=lambda item: (
            item.expected_width,
            item.worst_width,
            item.expected_cost,
            item.worst_cost,
            canonical(policy_data(item.policy)),
        ),
    )


def minimum_exact(frontier_value: Sequence[Candidate], *, worst: bool) -> Candidate | None:
    exact = [item for item in frontier_value if item.worst_width == 0 and item.expected_width == 0]
    if not exact:
        return None
    key = (
        (lambda item: (item.worst_cost, item.expected_cost, canonical(policy_data(item.policy))))
        if worst
        else (lambda item: (item.expected_cost, item.worst_cost, canonical(policy_data(item.policy))))
    )
    return min(exact, key=key)


def obstruction() -> dict[str, object]:
    names = ("recontact_nonresponse", "link_nonselected")
    for left, right in combinations(WORLDS, 2):
        if TARGET[left] == TARGET[right]:
            continue
        path: dict[str, str] = {}
        for experiment in names:
            common = sorted(
                observation
                for observation, probability in KERNEL[experiment][left].items()
                if probability > 0 and KERNEL[experiment][right].get(observation, Fraction(0)) > 0
            )
            if not common:
                break
            path[experiment] = common[0]
        else:
            return {
                "left": left,
                "right": right,
                "left_target": q(TARGET[left]),
                "right_target": q(TARGET[right]),
                "free_evidence": SNAPSHOT,
                "common_positive_path": path,
            }
    raise AssertionError("overlap obstruction missing")


def build_payload() -> dict[str, object]:
    for experiment, world_kernels in KERNEL.items():
        for world, kernel in world_kernels.items():
            if sum(kernel.values(), Fraction(0)) != 1:
                raise AssertionError(f"kernel normalization failed: {experiment}/{world}")

    expected = {
        Fraction(0): (1, (Fraction(1, 2), Fraction(1, 2), Fraction(0), Fraction(0))),
        Fraction(2): (2, (Fraction(1, 2), Fraction(19, 64), Fraction(2), Fraction(2))),
        Fraction(3): (3, (Fraction(1, 4), Fraction(1, 4), Fraction(3), Fraction(3))),
        Fraction(5): (10, (Fraction(1, 4), Fraction(3, 64), Fraction(5), Fraction(5))),
        Fraction(7): (11, (Fraction(0), Fraction(0), Fraction(7), Fraction(7))),
        Fraction(9): (15, (Fraction(0), Fraction(0), Fraction(9), Fraction(23, 4))),
    }
    packets = []
    for budget in BUDGETS:
        current = frontier(budget)
        selected = best(current)
        replayed = replay(selected.policy, normalize(PRIOR), frozenset(PAID), budget)
        if replayed.metrics() != selected.metrics():
            raise AssertionError("selected policy replay mismatch")
        expected_size, expected_metrics = expected[budget]
        if len(current) != expected_size or selected.metrics() != expected_metrics:
            raise AssertionError(f"budget {budget} changed")
        expected_exact = minimum_exact(current, worst=False)
        worst_exact = minimum_exact(current, worst=True)
        packets.append(
            {
                "budget": q(budget),
                "frontier_metrics": [
                    [q(metric) for metric in candidate.metrics()] for candidate in current
                ],
                "selected": selected.data(),
                "minimum_expected_cost_exact": None if expected_exact is None else expected_exact.data(),
                "minimum_worst_cost_exact": None if worst_exact is None else worst_exact.data(),
            }
        )

    exact_expected = minimum_exact(frontier(Fraction(9)), worst=False)
    exact_worst = minimum_exact(frontier(Fraction(9)), worst=True)
    if exact_expected is None or exact_worst is None:
        raise AssertionError("exact policies missing")
    if exact_expected.metrics() != (Fraction(0), Fraction(0), Fraction(9), Fraction(23, 4)):
        raise AssertionError("minimum expected-cost exact policy changed")
    if exact_worst.metrics() != (Fraction(0), Fraction(0), Fraction(7), Fraction(7)):
        raise AssertionError("minimum worst-cost exact policy changed")

    forged = Candidate(
        exact_expected.worst_width,
        exact_expected.expected_width,
        exact_expected.worst_cost,
        Fraction(0),
        exact_expected.policy,
    )
    if replay(forged.policy, normalize(PRIOR), frozenset(PAID), Fraction(9)).metrics() == forged.metrics():
        raise AssertionError("forged policy metrics accepted")

    failure = dict(posterior(normalize(PRIOR), "recontact_nonresponse", "FAIL"))
    expected_failure = {
        "M0_U0": Fraction(1, 6),
        "M0_U1": Fraction(1, 6),
        "M1_U0": Fraction(1, 3),
        "M1_U1": Fraction(1, 3),
    }
    if failure != expected_failure:
        raise AssertionError("failure posterior changed")

    return {
        "schema": "inference-power-compiler/missingness-selection-public-certificate/2",
        "problem": {
            "worlds": [
                {"id": world, "target": q(TARGET[world]), "prior": q(PRIOR[world])}
                for world in WORLDS
            ],
            "complete_case_snapshot": SNAPSHOT,
            "kernels": {
                experiment: {
                    world: {
                        observation: q(probability)
                        for observation, probability in sorted(kernel.items())
                    }
                    for world, kernel in world_kernels.items()
                }
                for experiment, world_kernels in KERNEL.items()
            },
            "costs": {experiment: q(cost) for experiment, cost in COST.items()},
        },
        "complete_case_interval": [[1, 4], [3, 4]],
        "naive_complete_case_mean": [1, 2],
        "failure_posterior": {world: q(weight) for world, weight in failure.items()},
        "budget_frontier": packets,
        "exact_pareto_budget_9": {
            "minimum_expected_cost": exact_expected.data(),
            "minimum_worst_cost": exact_worst.data(),
            "non_dominance": "PASS",
        },
        "overlap_obstruction": obstruction(),
        "power_gain": {
            "fixed_exact_expected_cost": [7, 1],
            "adaptive_exact_expected_cost": [23, 4],
            "expected_saving": [5, 4],
            "expected_saving_fraction": [5, 28],
            "budget_2_expected_width": [19, 64],
            "budget_5_expected_width": [3, 64],
        },
        "gates": {
            "complete_world_enumeration": "PASS",
            "kernel_normalization": "PASS",
            "exact_bayesian_updates": "PASS",
            "complete_finite_policy_search": "PASS",
            "pareto_frontier": "PASS",
            "selected_policy_replay": "PASS",
            "policy_tamper_rejection": "PASS",
            "overlap_obstruction": "PASS",
        },
        "scientific_boundary": (
            "Independent exact replay inside the declared finite rational kernel and "
            "no-repeat adaptive policy grammar; not a general theorem for all missing-data, "
            "selection-diagram or continuous POMDP models."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = build_payload()
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload, claimed = certificate.get("payload"), certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ["shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    if canonical(build_certificate()["payload"]) != canonical(payload):
        return ["semantic-replay"]
    return []


def report(certificate: Mapping[str, object]) -> dict[str, object]:
    payload = certificate["payload"]
    result = {
        "schema": "inference-power-compiler/missingness-selection-public-report/2",
        "complete_case_interval": payload["complete_case_interval"],
        "naive_complete_case_mean": payload["naive_complete_case_mean"],
        "failure_posterior": payload["failure_posterior"],
        "budget_frontier": [
            {
                "budget": packet["budget"],
                "frontier_size": len(packet["frontier_metrics"]),
                "selected": {
                    key: packet["selected"][key]
                    for key in (
                        "worst_width",
                        "expected_width",
                        "worst_cost",
                        "expected_cost",
                        "policy_sha256",
                    )
                },
                "exact_available": packet["minimum_expected_cost_exact"] is not None,
            }
            for packet in payload["budget_frontier"]
        ],
        "exact_pareto_budget_9": payload["exact_pareto_budget_9"],
        "overlap_obstruction": payload["overlap_obstruction"],
        "power_gain": payload["power_gain"],
        "gates": payload["gates"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
        "scientific_boundary": payload["scientific_boundary"],
    }
    result["sha256"] = digest(result)
    return result


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public certificate failed self replay")
    tampered = deepcopy(certificate)
    tampered["payload"]["power_gain"]["adaptive_exact_expected_cost"] = [0, 1]
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["power_gain"]["adaptive_exact_expected_cost"] = [0, 1]
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")
    result = report(certificate)
    write(ROOT / "MISSINGNESS_SELECTION_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "MISSINGNESS_SELECTION_PUBLIC_REPORT.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
