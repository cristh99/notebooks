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
PAID_ALL = ("do_A_0", "do_A_1", "joint_Y0_Y1")
PAID_SINGLE_WORLD = ("do_A_0", "do_A_1")


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def law_signature(values: Sequence[Fraction]) -> str:
    return "|".join(f"{value.numerator}/{value.denominator}" for value in values)


def enumerate_models() -> tuple[dict[str, object], ...]:
    models: list[dict[str, object]] = []
    for treatment in product((0, 1), repeat=2):
        for outcome in product((0, 1), repeat=4):
            name = "A" + "".join(map(str, treatment)) + "_Y" + "".join(
                map(str, outcome)
            )

            def response(action: int, latent: int) -> int:
                return outcome[2 * action + latent]

            observational = [Fraction(0) for _ in range(4)]
            do0 = [Fraction(0), Fraction(0)]
            do1 = [Fraction(0), Fraction(0)]
            joint = [Fraction(0) for _ in range(4)]
            for latent in (0, 1):
                action = treatment[latent]
                observed_outcome = response(action, latent)
                observational[2 * action + observed_outcome] += Fraction(1, 2)
                do0[response(0, latent)] += Fraction(1, 2)
                do1[response(1, latent)] += Fraction(1, 2)
                joint[
                    2 * response(0, latent) + response(1, latent)
                ] += Fraction(1, 2)
            models.append(
                {
                    "name": name,
                    "observational": tuple(observational),
                    "do_A_0": tuple(do0),
                    "do_A_1": tuple(do1),
                    "joint_Y0_Y1": tuple(joint),
                    "pns": joint[1],
                    "ace": do1[1] - do0[1],
                    "monotone": all(
                        response(1, latent) >= response(0, latent)
                        for latent in (0, 1)
                    ),
                }
            )
    return tuple(models)


@dataclass(frozen=True)
class Candidate:
    worst_width: Fraction
    expected_width: Fraction
    worst_cost: Fraction
    expected_cost: Fraction
    tree: Mapping[str, object]

    def metrics(self) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        return (
            self.worst_width,
            self.expected_width,
            self.worst_cost,
            self.expected_cost,
        )

    def summary(self) -> dict[str, object]:
        return {
            "worst_width": q(self.worst_width),
            "expected_width": q(self.expected_width),
            "worst_cost": q(self.worst_cost),
            "expected_cost": q(self.expected_cost),
            "tree_sha256": digest(self.tree),
        }

    def evidence(self) -> dict[str, object]:
        return {**self.summary(), "tree": self.tree}


class IndependentPlanner:
    def __init__(
        self,
        models: Sequence[Mapping[str, object]],
        include_joint_oracle: bool,
        combination_limit: int = 2_000_000,
    ) -> None:
        self.models = tuple(models)
        self.worlds = tuple(str(model["name"]) for model in self.models)
        self.by_world = {str(model["name"]): model for model in self.models}
        self.targets = {
            str(model["name"]): model["pns"] for model in self.models
        }
        self.prior = {
            world: Fraction(1, len(self.worlds)) for world in self.worlds
        }
        fields = ["observational", "do_A_0", "do_A_1"]
        self.costs = {
            "observational": Fraction(0),
            "do_A_0": Fraction(3),
            "do_A_1": Fraction(3),
        }
        if include_joint_oracle:
            fields.append("joint_Y0_Y1")
            self.costs["joint_Y0_Y1"] = Fraction(9)
        self.signatures = {
            field: {
                world: law_signature(self.by_world[world][field])
                for world in self.worlds
            }
            for field in fields
        }
        self.combination_limit = combination_limit
        if len(set(self.worlds)) != len(self.worlds):
            raise ValueError("worlds must be unique")
        if not self.worlds or combination_limit <= 0:
            raise ValueError("invalid finite control")

    def problem_data(self) -> dict[str, object]:
        return {
            "worlds": [
                {
                    "id": world,
                    "target": q(self.targets[world]),
                    "prior": q(self.prior[world]),
                }
                for world in self.worlds
            ],
            "experiments": [
                {
                    "name": field,
                    "cost": q(self.costs[field]),
                    "signatures": {
                        world: self.signatures[field][world]
                        for world in self.worlds
                    },
                }
                for field in sorted(self.signatures)
            ],
            "combination_limit": self.combination_limit,
        }

    def mass(self, belief: Sequence[str]) -> Fraction:
        return sum((self.prior[world] for world in belief), Fraction(0))

    def interval(self, belief: Sequence[str]) -> tuple[Fraction, Fraction]:
        if not belief:
            raise ValueError("belief must be nonempty")
        values = tuple(self.targets[world] for world in belief)
        return min(values), max(values)

    def partition(
        self, belief: Sequence[str], field: str
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        groups: dict[str, list[str]] = {}
        for world in belief:
            groups.setdefault(self.signatures[field][world], []).append(world)
        return tuple(
            (signature, tuple(sorted(group)))
            for signature, group in sorted(groups.items())
        )

    @staticmethod
    def dominates(left: Candidate, right: Candidate) -> bool:
        left_metrics = left.metrics()
        right_metrics = right.metrics()
        return all(
            left_value <= right_value
            for left_value, right_value in zip(left_metrics, right_metrics)
        ) and any(
            left_value < right_value
            for left_value, right_value in zip(left_metrics, right_metrics)
        )

    @classmethod
    def pareto(cls, candidates: Sequence[Candidate]) -> tuple[Candidate, ...]:
        canonical_by_metrics: dict[
            tuple[Fraction, Fraction, Fraction, Fraction], Candidate
        ] = {}
        for candidate in candidates:
            key = candidate.metrics()
            incumbent = canonical_by_metrics.get(key)
            if incumbent is None or canonical(candidate.tree) < canonical(
                incumbent.tree
            ):
                canonical_by_metrics[key] = candidate
        unique = tuple(canonical_by_metrics.values())
        frontier = tuple(
            candidate
            for candidate in unique
            if not any(
                other is not candidate and cls.dominates(other, candidate)
                for other in unique
            )
        )
        return tuple(
            sorted(
                frontier,
                key=lambda candidate: (
                    candidate.expected_width,
                    candidate.worst_width,
                    candidate.expected_cost,
                    candidate.worst_cost,
                    canonical(candidate.tree),
                ),
            )
        )

    def state_frontier(
        self,
        belief: Sequence[str],
        available: Sequence[str],
        budget: Fraction,
    ) -> tuple[Candidate, ...]:
        belief_tuple = tuple(sorted(belief))
        available_tuple = tuple(sorted(available))
        if budget < 0 or not belief_tuple:
            raise ValueError("invalid state")
        if not set(available_tuple) <= set(self.signatures):
            raise ValueError("unknown experiment")
        combinations_examined = 0

        @lru_cache(maxsize=None)
        def solve(
            current_belief: tuple[str, ...],
            current_available: tuple[str, ...],
            remaining_budget: Fraction,
        ) -> tuple[Candidate, ...]:
            nonlocal combinations_examined
            lower, upper = self.interval(current_belief)
            current_width = upper - lower
            candidates: list[Candidate] = [
                Candidate(
                    current_width,
                    current_width,
                    Fraction(0),
                    Fraction(0),
                    {
                        "kind": "stop",
                        "belief": list(current_belief),
                        "belief_mass": q(self.mass(current_belief)),
                        "certificate": (
                            "POINT_IDENTIFICATION"
                            if current_width == 0
                            else "SHARP_PARTIAL_IDENTIFICATION"
                        ),
                        "interval": [q(lower), q(upper)],
                    },
                )
            ]
            current_mass = self.mass(current_belief)
            for experiment in current_available:
                cost = self.costs[experiment]
                if cost > remaining_budget:
                    continue
                groups = self.partition(current_belief, experiment)
                if len(groups) <= 1:
                    continue
                remaining = tuple(
                    name for name in current_available if name != experiment
                )
                child_frontiers = tuple(
                    solve(group, remaining, remaining_budget - cost)
                    for _signature, group in groups
                )
                local_combinations = 1
                for child_frontier in child_frontiers:
                    local_combinations *= len(child_frontier)
                combinations_examined += local_combinations
                if combinations_examined > self.combination_limit:
                    raise RuntimeError("policy combination limit exceeded")
                for children in product(*child_frontiers):
                    expected_width = sum(
                        (
                            self.mass(group)
                            / current_mass
                            * child.expected_width
                            for (_signature, group), child in zip(
                                groups, children
                            )
                        ),
                        Fraction(0),
                    )
                    expected_cost = cost + sum(
                        (
                            self.mass(group)
                            / current_mass
                            * child.expected_cost
                            for (_signature, group), child in zip(
                                groups, children
                            )
                        ),
                        Fraction(0),
                    )
                    candidates.append(
                        Candidate(
                            max(child.worst_width for child in children),
                            expected_width,
                            cost + max(child.worst_cost for child in children),
                            expected_cost,
                            {
                                "kind": "experiment",
                                "belief": list(current_belief),
                                "belief_mass": q(current_mass),
                                "experiment": experiment,
                                "experiment_cost": q(cost),
                                "remaining_budget_before": q(remaining_budget),
                                "children": {
                                    signature: child.tree
                                    for (signature, _group), child in zip(
                                        groups, children
                                    )
                                },
                            },
                        )
                    )
            return self.pareto(candidates)

        return solve(belief_tuple, available_tuple, budget)

    def frontier_after_observation(
        self, paid: Sequence[str], budget: Fraction
    ) -> tuple[Candidate, ...]:
        groups = self.partition(self.worlds, "observational")
        child_frontiers = tuple(
            self.state_frontier(group, paid, budget)
            for _signature, group in groups
        )
        combinations_examined = 1
        for child_frontier in child_frontiers:
            combinations_examined *= len(child_frontier)
        if combinations_examined > self.combination_limit:
            raise RuntimeError("root policy combination limit exceeded")
        candidates: list[Candidate] = []
        for children in product(*child_frontiers):
            candidates.append(
                Candidate(
                    max(child.worst_width for child in children),
                    sum(
                        (
                            self.mass(group) * child.expected_width
                            for (_signature, group), child in zip(
                                groups, children
                            )
                        ),
                        Fraction(0),
                    ),
                    max(child.worst_cost for child in children),
                    sum(
                        (
                            self.mass(group) * child.expected_cost
                            for (_signature, group), child in zip(
                                groups, children
                            )
                        ),
                        Fraction(0),
                    ),
                    {
                        "kind": "free_evidence",
                        "experiment": "observational",
                        "children": {
                            signature: child.tree
                            for (signature, _group), child in zip(
                                groups, children
                            )
                        },
                    },
                )
            )
        return self.pareto(candidates)

    @staticmethod
    def best_width(frontier: Sequence[Candidate]) -> Candidate:
        return min(
            frontier,
            key=lambda candidate: (
                candidate.expected_width,
                candidate.worst_width,
                candidate.expected_cost,
                candidate.worst_cost,
                canonical(candidate.tree),
            ),
        )

    @staticmethod
    def exact_min_expected(
        frontier: Sequence[Candidate],
    ) -> Candidate | None:
        exact = [
            candidate
            for candidate in frontier
            if candidate.expected_width == 0 and candidate.worst_width == 0
        ]
        return (
            None
            if not exact
            else min(
                exact,
                key=lambda candidate: (
                    candidate.expected_cost,
                    candidate.worst_cost,
                    canonical(candidate.tree),
                ),
            )
        )

    @staticmethod
    def exact_min_worst(frontier: Sequence[Candidate]) -> Candidate | None:
        exact = [
            candidate
            for candidate in frontier
            if candidate.expected_width == 0 and candidate.worst_width == 0
        ]
        return (
            None
            if not exact
            else min(
                exact,
                key=lambda candidate: (
                    candidate.worst_cost,
                    candidate.expected_cost,
                    canonical(candidate.tree),
                ),
            )
        )

    def obstruction(self, fields: Sequence[str]) -> dict[str, object] | None:
        candidates: list[dict[str, object]] = []
        for left, right in combinations(sorted(self.worlds), 2):
            if self.targets[left] == self.targets[right]:
                continue
            if all(
                self.signatures[field][left]
                == self.signatures[field][right]
                for field in fields
            ):
                candidates.append(
                    {
                        "left": left,
                        "right": right,
                        "left_target": q(self.targets[left]),
                        "right_target": q(self.targets[right]),
                        "evidence": list(fields),
                        "signatures": {
                            field: self.signatures[field][left]
                            for field in fields
                        },
                    }
                )
        return (
            None
            if not candidates
            else min(
                candidates,
                key=lambda candidate: (
                    candidate["left"],
                    candidate["right"],
                ),
            )
        )

    def replay(
        self,
        candidate: Candidate,
        paid: Sequence[str],
        budget: Fraction,
    ) -> Candidate:
        paid_set = frozenset(paid)

        def visit(
            node: Mapping[str, object],
            belief: tuple[str, ...],
            available: frozenset[str],
            remaining_budget: Fraction,
        ) -> Candidate:
            kind = node.get("kind")
            if kind == "stop":
                lower, upper = self.interval(belief)
                width = upper - lower
                if node.get("belief") != list(belief):
                    raise AssertionError("stop belief mismatch")
                if node.get("interval") != [q(lower), q(upper)]:
                    raise AssertionError("stop interval mismatch")
                return Candidate(
                    width, width, Fraction(0), Fraction(0), node
                )
            if kind != "experiment":
                raise AssertionError("invalid policy node")
            experiment = node.get("experiment")
            if not isinstance(experiment, str) or experiment not in available:
                raise AssertionError("invalid or repeated experiment")
            cost = self.costs[experiment]
            if cost > remaining_budget:
                raise AssertionError("budget exceeded")
            groups = self.partition(belief, experiment)
            children_raw = node.get("children")
            if not isinstance(children_raw, Mapping):
                raise AssertionError("children missing")
            if set(children_raw) != {
                signature for signature, _group in groups
            }:
                raise AssertionError("child signature mismatch")
            packets: list[tuple[tuple[str, ...], Candidate]] = []
            next_available = available - {experiment}
            for signature, group in groups:
                child = children_raw[signature]
                if not isinstance(child, Mapping):
                    raise AssertionError("malformed child")
                packets.append(
                    (
                        group,
                        visit(
                            child,
                            group,
                            next_available,
                            remaining_budget - cost,
                        ),
                    )
                )
            current_mass = self.mass(belief)
            return Candidate(
                max(child.worst_width for _group, child in packets),
                sum(
                    (
                        self.mass(group)
                        / current_mass
                        * child.expected_width
                        for group, child in packets
                    ),
                    Fraction(0),
                ),
                cost + max(child.worst_cost for _group, child in packets),
                cost
                + sum(
                    (
                        self.mass(group)
                        / current_mass
                        * child.expected_cost
                        for group, child in packets
                    ),
                    Fraction(0),
                ),
                node,
            )

        root = candidate.tree
        if root.get("kind") != "free_evidence":
            raise AssertionError("free evidence root missing")
        children_raw = root.get("children")
        if not isinstance(children_raw, Mapping):
            raise AssertionError("free root children missing")
        groups = self.partition(self.worlds, "observational")
        if set(children_raw) != {signature for signature, _group in groups}:
            raise AssertionError("free root signature mismatch")
        packets: list[tuple[tuple[str, ...], Candidate]] = []
        for signature, group in groups:
            child = children_raw[signature]
            if not isinstance(child, Mapping):
                raise AssertionError("malformed free-root child")
            packets.append((group, visit(child, group, paid_set, budget)))
        rebuilt = Candidate(
            max(child.worst_width for _group, child in packets),
            sum(
                (
                    self.mass(group) * child.expected_width
                    for group, child in packets
                ),
                Fraction(0),
            ),
            max(child.worst_cost for _group, child in packets),
            sum(
                (
                    self.mass(group) * child.expected_cost
                    for group, child in packets
                ),
                Fraction(0),
            ),
            root,
        )
        if rebuilt.metrics() != candidate.metrics():
            raise AssertionError("policy metric replay mismatch")
        if digest(rebuilt.tree) != digest(candidate.tree):
            raise AssertionError("policy tree replay mismatch")
        return rebuilt


def budget_packet(
    planner: IndependentPlanner, budget: Fraction
) -> dict[str, object]:
    frontier = planner.frontier_after_observation(PAID_ALL, budget)
    selected = planner.best_width(frontier)
    planner.replay(selected, PAID_ALL, budget)
    exact_expected = planner.exact_min_expected(frontier)
    exact_worst = planner.exact_min_worst(frontier)
    return {
        "budget": q(budget),
        "frontier_size": len(frontier),
        "frontier": [candidate.summary() for candidate in frontier],
        "selected": selected.evidence(),
        "exact_available": exact_expected is not None,
        "minimum_expected_exact": (
            None if exact_expected is None else exact_expected.evidence()
        ),
        "minimum_worst_exact": (
            None if exact_worst is None else exact_worst.evidence()
        ),
        "semantic_replay": "PASS",
    }


def compile_payload() -> dict[str, object]:
    models = enumerate_models()
    unrestricted = IndependentPlanner(models, include_joint_oracle=True)
    budgets = tuple(Fraction(value) for value in (0, 3, 6, 9, 12))
    packets = [budget_packet(unrestricted, budget) for budget in budgets]
    by_budget = {Fraction(*packet["budget"]): packet for packet in packets}

    expected_frontier_sizes = {0: 1, 3: 8, 6: 14, 9: 16, 12: 18}
    expected_selected = {
        0: (Fraction(1), Fraction(1, 2), Fraction(0), Fraction(0)),
        3: (Fraction(1, 2), Fraction(1, 8), Fraction(3), Fraction(9, 4)),
        6: (Fraction(1, 2), Fraction(1, 16), Fraction(6), Fraction(21, 8)),
        9: (Fraction(0), Fraction(0), Fraction(9), Fraction(33, 8)),
        12: (Fraction(0), Fraction(0), Fraction(12), Fraction(15, 4)),
    }
    for budget_value in expected_frontier_sizes:
        packet = by_budget[Fraction(budget_value)]
        if packet["frontier_size"] != expected_frontier_sizes[budget_value]:
            raise AssertionError("Pareto frontier size changed")
        selected = packet["selected"]
        actual = (
            Fraction(*selected["worst_width"]),
            Fraction(*selected["expected_width"]),
            Fraction(*selected["worst_cost"]),
            Fraction(*selected["expected_cost"]),
        )
        if actual != expected_selected[budget_value]:
            raise AssertionError(
                f"budget {budget_value} selected metrics changed: {actual}"
            )

    budget12 = by_budget[Fraction(12)]
    expected_min = budget12["minimum_expected_exact"]
    worst_min = budget12["minimum_worst_exact"]
    if not isinstance(expected_min, Mapping) or not isinstance(
        worst_min, Mapping
    ):
        raise AssertionError("budget 12 exact policies missing")
    if (
        Fraction(*expected_min["expected_cost"]),
        Fraction(*expected_min["worst_cost"]),
    ) != (Fraction(15, 4), Fraction(12)):
        raise AssertionError("minimum expected exact policy changed")
    if (
        Fraction(*worst_min["expected_cost"]),
        Fraction(*worst_min["worst_cost"]),
    ) != (Fraction(33, 8), Fraction(9)):
        raise AssertionError("minimum worst exact policy changed")
    if not (
        Fraction(*expected_min["expected_cost"])
        < Fraction(*worst_min["expected_cost"])
        and Fraction(*worst_min["worst_cost"])
        < Fraction(*expected_min["worst_cost"])
    ):
        raise AssertionError("exact policies are not a Pareto tradeoff")

    no_joint = IndependentPlanner(models, include_joint_oracle=False)
    no_joint_frontier = no_joint.frontier_after_observation(
        PAID_SINGLE_WORLD, Fraction(12)
    )
    no_joint_best = no_joint.best_width(no_joint_frontier)
    no_joint.replay(no_joint_best, PAID_SINGLE_WORLD, Fraction(12))
    if no_joint.exact_min_expected(no_joint_frontier) is not None:
        raise AssertionError("single-world evidence unexpectedly identifies PNS")
    if len(no_joint_frontier) != 14 or no_joint_best.metrics() != (
        Fraction(1, 2),
        Fraction(1, 16),
        Fraction(6),
        Fraction(21, 8),
    ):
        raise AssertionError("single-world partial frontier changed")
    obstruction = no_joint.obstruction(
        ("observational", "do_A_0", "do_A_1")
    )
    if obstruction is None or (
        obstruction["left"], obstruction["right"]
    ) != ("A00_Y0101", "A00_Y0110"):
        raise AssertionError("canonical counterfactual obstruction changed")

    monotone_models = tuple(model for model in models if model["monotone"])
    monotone = IndependentPlanner(
        monotone_models, include_joint_oracle=False
    )
    monotone_frontier = monotone.frontier_after_observation(
        PAID_SINGLE_WORLD, Fraction(6)
    )
    monotone_exact = monotone.exact_min_expected(monotone_frontier)
    if monotone_exact is None:
        raise AssertionError("monotonicity must close PNS")
    monotone.replay(monotone_exact, PAID_SINGLE_WORLD, Fraction(6))
    if len(monotone_frontier) != 11 or monotone_exact.metrics() != (
        Fraction(0),
        Fraction(0),
        Fraction(6),
        Fraction(10, 3),
    ):
        raise AssertionError("monotone exact policy changed")
    if not all(model["pns"] == model["ace"] for model in monotone_models):
        raise AssertionError("PNS=ACE failed under monotonicity")

    selected_budget12 = Candidate(
        Fraction(*by_budget[Fraction(12)]["selected"]["worst_width"]),
        Fraction(*by_budget[Fraction(12)]["selected"]["expected_width"]),
        Fraction(*by_budget[Fraction(12)]["selected"]["worst_cost"]),
        Fraction(*by_budget[Fraction(12)]["selected"]["expected_cost"]),
        by_budget[Fraction(12)]["selected"]["tree"],
    )
    tampered_policy = Candidate(
        selected_budget12.worst_width,
        selected_budget12.expected_width,
        selected_budget12.worst_cost,
        Fraction(0),
        selected_budget12.tree,
    )
    policy_tamper_rejected = False
    try:
        unrestricted.replay(tampered_policy, PAID_ALL, Fraction(12))
    except AssertionError:
        policy_tamper_rejected = True
    if not policy_tamper_rejected:
        raise AssertionError("tampered policy was accepted")

    return {
        "schema": "epistemic-policy-independent-public-verification/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": "96d080cf37b66f32ed6cf14c5c72692fb06ddddc",
            "planner_blob": "359490ad24e9421489b7fa0def2e5d6ee0ff3c54",
            "runner_blob": "d0d6257c2da39b843d71bd7b0f02fdc9499d6b0f",
            "lean_blob": "c7bdb8e632c59389c56edb58a92348d62f1682c1",
            "workflow_blob": "3dcf232dd7d057ccca621b92893fe73d92d1fd1c",
        },
        "problem": unrestricted.problem_data(),
        "budget_frontier": packets,
        "exact_pareto_budget_12": {
            "minimum_expected_cost": expected_min,
            "minimum_worst_cost": worst_min,
            "non_dominance": "PASS",
        },
        "single_world_boundary": {
            "status": "NOT_POINT_IDENTIFIED",
            "frontier_size": len(no_joint_frontier),
            "best_partial_policy": no_joint_best.evidence(),
            "obstruction": obstruction,
        },
        "monotonicity_closure": {
            "worlds": len(monotone_models),
            "frontier_size": len(monotone_frontier),
            "exact_policy": monotone_exact.evidence(),
            "status": "POINT_IDENTIFIED",
        },
        "power_gain": {
            "fixed_joint_oracle_cost": [9, 1],
            "budget_9_exact_expected_cost": [33, 8],
            "budget_9_expected_saving": [39, 8],
            "budget_9_expected_saving_fraction": [13, 24],
            "budget_12_exact_expected_cost": [15, 4],
            "budget_12_expected_saving": [21, 4],
            "budget_12_expected_saving_fraction": [7, 12],
            "monotone_fixed_both_cost": [6, 1],
            "monotone_exact_expected_cost": [10, 3],
            "monotone_expected_saving": [8, 3],
            "monotone_expected_saving_fraction": [4, 9],
        },
        "gates": {
            "complete_model_enumeration": "PASS",
            "complete_finite_policy_search": "PASS",
            "budget_feasibility": "PASS",
            "sharp_leaf_intervals": "PASS",
            "pareto_frontier": "PASS",
            "selected_policy_replay": "PASS",
            "policy_tamper_rejection": "PASS",
            "single_world_obstruction": "PASS",
            "monotonicity_closure": "PASS",
        },
        "scientific_boundary": (
            "Independent exact replay inside the finite deterministic evidence "
            "and policy grammar. It is not a completeness theorem for arbitrary "
            "POMDPs, continuous experiments or measurable decision theory."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = compile_payload()
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload = certificate.get("payload")
    claimed = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ["certificate-shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    if canonical(payload) != canonical(compile_payload()):
        return ["semantic-replay"]
    return []


def build_report(certificate: Mapping[str, object]) -> dict[str, object]:
    payload = certificate["payload"]
    return {
        "schema": "inference-power-compiler/epistemic-policy-public-report/1",
        "budget_frontier": [
            {
                "budget": packet["budget"],
                "frontier_size": packet["frontier_size"],
                "selected": {
                    key: packet["selected"][key]
                    for key in (
                        "worst_width",
                        "expected_width",
                        "worst_cost",
                        "expected_cost",
                        "tree_sha256",
                    )
                },
                "exact_available": packet["exact_available"],
            }
            for packet in payload["budget_frontier"]
        ],
        "exact_pareto_budget_12": payload["exact_pareto_budget_12"],
        "single_world_boundary": payload["single_world_boundary"],
        "monotonicity_closure": payload["monotonicity_closure"],
        "power_gain": payload["power_gain"],
        "gates": payload["gates"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
        "scientific_boundary": payload["scientific_boundary"],
    }


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public epistemic certificate replay failed")

    tampered = deepcopy(certificate)
    tampered["payload"]["power_gain"]["budget_12_exact_expected_cost"] = [0, 1]
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper was accepted")

    forged = deepcopy(certificate)
    forged["payload"]["power_gain"]["budget_12_exact_expected_cost"] = [0, 1]
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery was accepted")

    report = build_report(certificate)
    report["sha256"] = digest(report)
    (ROOT / "EPISTEMIC_POLICY_PUBLIC_CERTIFICATE.json").write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (ROOT / "EPISTEMIC_POLICY_PUBLIC_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
