from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from heapq import heappop, heappush
from itertools import combinations, count, product
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent

PRIVATE_BINDING = {
    "repository": "cristh99/my_first_repository",
    "pull_request": 108,
    "head": "fd717ce86dc54ae7f9279e10df85ce1be74554c4",
    "git_blobs": {
        "router": "0c70bc8afd5aa3ff616abd4f8a80070ebdc54824",
        "tests": "f384334c61256f641a2544d2c0a0be8f9d7ae736",
        "runner": "04d090d68f07e4e5f1bb9418e2a1c194cb768b68",
        "lean": "aebf695a80c3c0a1739b3790979210abb27a7813",
        "workflow": "99cf036060b189e9ef67bee988ff2fb327e364a3",
    },
}

GOAL_OUTPUTS: dict[str, frozenset[str]] = {
    "causal_effect": frozenset(
        {"identified_estimand", "point_estimate", "uncertainty"}
    ),
    "causal_bounds": frozenset({"sharp_identified_set", "uncertainty"}),
    "decision": frozenset({"decision_rule", "optimality"}),
    "sequential_monitoring": frozenset({"anytime_validity", "uncertainty"}),
    "active_evidence": frozenset({"evidence_policy"}),
    "lower_bound": frozenset({"lower_bound"}),
    "robust_estimation": frozenset(
        {"point_estimate", "uncertainty", "robust_guarantee"}
    ),
    "change_detection": frozenset({"change_detection", "anytime_validity"}),
    "multiscale_estimation": frozenset(
        {"adaptive_resolution", "uncertainty"}
    ),
    "full_inference": frozenset(
        {
            "identified_estimand",
            "point_estimate",
            "uncertainty",
            "optimality",
            "formal_certificate",
        }
    ),
    "experiment_comparison": frozenset({"experiment_comparison"}),
    "transportability": frozenset({"transported_estimand", "uncertainty"}),
    "missing_data": frozenset({"sharp_identified_set", "evidence_policy"}),
    "custom": frozenset(),
}

CONTRADICTIONS = (
    ("graph_known", "graph_unknown"),
    ("iid", "arbitrary_dependence"),
    ("interventions_available", "interventions_forbidden"),
    ("finite", "infinite_support_only"),
    ("sequential", "single_terminal_analysis_only"),
    ("overlap", "positivity_failure"),
    ("signed_manifest", "unverifiable_provenance"),
)

DIAGNOSTIC_COSTS = {
    "finite": Fraction(1),
    "rational": Fraction(1),
    "graph_known": Fraction(5),
    "scm_family": Fraction(5),
    "world_family": Fraction(4),
    "laws_known": Fraction(5),
    "loss_known": Fraction(2),
    "observational_distribution": Fraction(3),
    "experiments_declared": Fraction(2),
    "costs_declared": Fraction(1),
    "crossfit_provenance": Fraction(2),
    "overlap": Fraction(2),
    "bounded_score": Fraction(1),
    "predictable_strategy": Fraction(2),
    "contamination_model": Fraction(3),
    "missingness_model": Fraction(4),
    "selection_model": Fraction(4),
    "source_target_domains": Fraction(4),
    "invariance_audit": Fraction(4),
    "decision_problem": Fraction(2),
    "multiscale": Fraction(2),
    "bias_envelope": Fraction(3),
    "signed_manifest": Fraction(3),
    "centered_scores": Fraction(2),
    "conditional_independence": Fraction(4),
    "semiparametric": Fraction(3),
    "sequential": Fraction(2),
    "causal": Fraction(2),
}

TERMINALS = (
    "SOLVED",
    "IMPOSSIBLE",
    "UNKNOWN",
    "BLOCKED",
    "UNDERSPECIFIED",
    "BUDGET_EXHAUSTED",
    "UNSAFE",
)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def parse_q(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("rational must be [numerator, denominator]")
    numerator, denominator = value
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        raise ValueError("rational entries must be integers")
    if denominator <= 0:
        raise ValueError("rational denominator must be positive")
    return Fraction(numerator, denominator)


@dataclass(frozen=True)
class Capability:
    name: str
    requires: frozenset[str]
    provides: frozenset[str]
    cost: Fraction
    executor: str

    def data(self) -> dict[str, object]:
        return {
            "name": self.name,
            "requires": sorted(self.requires),
            "provides": sorted(self.provides),
            "cost": q(self.cost),
            "executor": self.executor,
        }


@dataclass(frozen=True)
class Problem:
    name: str
    goal: str
    facts: frozenset[str]
    budget: Fraction
    requested_outputs: frozenset[str] = frozenset()
    blocked: frozenset[str] = frozenset()
    witness: Mapping[str, object] | None = None

    @property
    def outputs(self) -> frozenset[str]:
        if self.goal not in GOAL_OUTPUTS:
            raise ValueError(f"unknown goal: {self.goal}")
        return frozenset(set(GOAL_OUTPUTS[self.goal]) | set(self.requested_outputs))

    def data(self) -> dict[str, object]:
        return {
            "name": self.name,
            "goal": self.goal,
            "facts": sorted(self.facts),
            "budget": q(self.budget),
            "requested_outputs": sorted(self.requested_outputs),
            "blocked": sorted(self.blocked),
            "witness": self.witness,
        }

    @classmethod
    def from_data(cls, data: Mapping[str, object]) -> "Problem":
        return cls(
            name=str(data["name"]),
            goal=str(data["goal"]),
            facts=frozenset(str(item) for item in data.get("facts", [])),
            budget=parse_q(data["budget"]),
            requested_outputs=frozenset(
                str(item) for item in data.get("requested_outputs", [])
            ),
            blocked=frozenset(str(item) for item in data.get("blocked", [])),
            witness=data.get("witness")
            if isinstance(data.get("witness"), Mapping)
            else None,
        )


def cap(
    name: str,
    requires: Iterable[str],
    provides: Iterable[str],
    cost: int,
    executor: str,
) -> Capability:
    return Capability(
        name,
        frozenset(requires),
        frozenset(provides),
        Fraction(cost),
        executor,
    )


def registry() -> tuple[Capability, ...]:
    values = (
        cap(
            "finite_causal_id",
            ("causal", "finite", "graph_known"),
            ("identified_estimand", "impossibility_witness", "formal_certificate"),
            8,
            "admg_id_compiler",
        ),
        cap(
            "finite_scm_enumeration",
            ("causal", "finite", "scm_family"),
            (
                "identified_estimand",
                "evidence_policy",
                "impossibility_witness",
                "formal_certificate",
            ),
            10,
            "finite_scm_compiler",
        ),
        cap(
            "causal_adjustment",
            ("causal", "finite", "graph_known", "observational_distribution"),
            ("identified_estimand", "point_estimate", "formal_certificate"),
            8,
            "causal_adjustment_compiler",
        ),
        cap(
            "partial_identification",
            ("finite", "world_family"),
            ("sharp_identified_set", "uncertainty", "formal_certificate"),
            7,
            "partial_identification_compiler",
        ),
        cap(
            "finite_sample_minimax",
            ("finite", "rational", "loss_known", "laws_known"),
            ("decision_rule", "optimality", "uncertainty", "formal_certificate"),
            12,
            "finite_sample_design",
        ),
        cap(
            "lower_bound_metacompiler",
            ("finite", "rational", "laws_known"),
            ("lower_bound", "optimality", "formal_certificate"),
            10,
            "lower_bound_metacompiler",
        ),
        cap(
            "epistemic_policy",
            ("finite", "world_family", "experiments_declared", "costs_declared"),
            ("evidence_policy", "sharp_identified_set", "formal_certificate"),
            12,
            "epistemic_policy_compiler",
        ),
        cap(
            "crossfit_finite",
            (
                "causal",
                "finite",
                "identified_estimand",
                "crossfit_provenance",
                "overlap",
            ),
            ("point_estimate", "uncertainty", "formal_certificate"),
            10,
            "crossfit_compiler",
        ),
        cap(
            "semiparametric_anytime",
            (
                "causal",
                "semiparametric",
                "identified_estimand",
                "crossfit_provenance",
                "overlap",
                "sequential",
            ),
            (
                "point_estimate",
                "uncertainty",
                "anytime_validity",
                "formal_certificate",
            ),
            18,
            "semiparametric_anytime_compiler",
        ),
        cap(
            "adaptive_eprocess",
            ("sequential", "bounded_score", "predictable_strategy"),
            ("anytime_validity", "uncertainty", "formal_certificate"),
            8,
            "adaptive_eprocess",
        ),
        cap(
            "robust_contamination",
            ("finite", "contamination_model"),
            (
                "robust_guarantee",
                "uncertainty",
                "impossibility_witness",
                "formal_certificate",
            ),
            8,
            "robust_contamination",
        ),
        cap(
            "missingness_selection",
            ("finite", "missingness_model", "selection_model"),
            ("sharp_identified_set", "evidence_policy", "formal_certificate"),
            11,
            "missingness_selection_compiler",
        ),
        cap(
            "transportability",
            ("causal", "finite", "source_target_domains", "invariance_audit"),
            (
                "transported_estimand",
                "uncertainty",
                "evidence_policy",
                "formal_certificate",
            ),
            12,
            "transportability_compiler",
        ),
        cap(
            "blackwell_comparison",
            ("finite", "experiments_declared", "decision_problem"),
            ("experiment_comparison", "decision_rule", "formal_certificate"),
            9,
            "blackwell_compiler",
        ),
        cap(
            "graphical_multiscale",
            ("finite", "multiscale", "bias_envelope", "graph_known"),
            ("adaptive_resolution", "uncertainty", "formal_certificate"),
            14,
            "graphical_dependent_multiscale",
        ),
        cap(
            "unknown_changepoint",
            ("sequential", "signed_manifest", "predictable_strategy", "bounded_score"),
            ("change_detection", "anytime_validity", "formal_certificate"),
            14,
            "unknown_changepoint_compiler",
        ),
        cap(
            "conditional_clt",
            ("finite", "centered_scores", "conditional_independence"),
            ("uncertainty", "formal_certificate"),
            8,
            "conditional_clt_compiler",
        ),
        cap(
            "exact_interval",
            ("finite", "rational", "laws_known"),
            ("uncertainty", "formal_certificate"),
            7,
            "exact_interval_compiler",
        ),
    )
    return tuple(sorted(values, key=lambda item: item.name))


class IndependentRouter:
    def __init__(self) -> None:
        self.capabilities = registry()
        self.by_name = {item.name: item for item in self.capabilities}
        self.registry_hash = digest([item.data() for item in self.capabilities])

    @staticmethod
    def contradictions(facts: Iterable[str]) -> list[list[str]]:
        values = set(facts)
        return [list(pair) for pair in CONTRADICTIONS if set(pair) <= values]

    def shortest_portfolio(
        self,
        problem: Problem,
        *,
        extra_facts: Iterable[str] = (),
    ) -> dict[str, object] | None:
        start = frozenset(set(problem.facts) | set(extra_facts))
        serial = count()
        queue: list[
            tuple[Fraction, int, tuple[str, ...], int, frozenset[str]]
        ] = []
        heappush(queue, (Fraction(0), 0, (), next(serial), start))
        best: dict[frozenset[str], tuple[Fraction, int, tuple[str, ...]]] = {
            start: (Fraction(0), 0, ())
        }
        while queue:
            cost, steps, path, _serial, facts = heappop(queue)
            if best.get(facts) != (cost, steps, path):
                continue
            if problem.outputs <= facts:
                return {
                    "capabilities": list(path),
                    "execution_order": list(path),
                    "cost": q(cost),
                    "available_facts": sorted(facts),
                    "dispatch": [
                        {
                            "capability": name,
                            "executor": self.by_name[name].executor,
                            "cost": q(self.by_name[name].cost),
                        }
                        for name in path
                    ],
                }
            for capability in self.capabilities:
                if capability.name in problem.blocked:
                    continue
                if capability.name in path:
                    continue
                if not capability.requires <= facts:
                    continue
                new_facts = frozenset(set(facts) | set(capability.provides))
                if new_facts == facts:
                    continue
                new_cost = cost + capability.cost
                new_path = path + (capability.name,)
                candidate = (new_cost, steps + 1, new_path)
                incumbent = best.get(new_facts)
                if incumbent is None or candidate < incumbent:
                    best[new_facts] = candidate
                    heappush(
                        queue,
                        (new_cost, steps + 1, new_path, next(serial), new_facts),
                    )
        return None

    def relevant_capabilities(self, outputs: frozenset[str]) -> tuple[Capability, ...]:
        needed = set(outputs)
        relevant: set[str] = set()
        changed = True
        while changed:
            changed = False
            for capability in self.capabilities:
                if capability.name in relevant:
                    continue
                if capability.provides & needed:
                    relevant.add(capability.name)
                    needed.update(capability.requires)
                    changed = True
        return tuple(item for item in self.capabilities if item.name in relevant)

    def minimal_missing(
        self, problem: Problem
    ) -> tuple[frozenset[str], dict[str, object]] | None:
        relevant = self.relevant_capabilities(problem.outputs)
        best: tuple[int, Fraction, Fraction, tuple[str, ...], frozenset[str], dict[str, object]] | None = None
        for size in range(len(relevant) + 1):
            for subset in combinations(relevant, size):
                produced = set().union(*(item.provides for item in subset)) if subset else set()
                if not problem.outputs <= set(problem.facts) | produced:
                    continue
                missing = frozenset(
                    (set().union(*(item.requires for item in subset)) if subset else set())
                    - set(problem.facts)
                    - produced
                )
                conditional = self.shortest_portfolio(problem, extra_facts=missing)
                if conditional is None:
                    continue
                diagnostic_cost = sum(
                    (DIAGNOSTIC_COSTS.get(item, Fraction(5)) for item in missing),
                    Fraction(0),
                )
                names = tuple(conditional["capabilities"])
                candidate = (
                    len(missing),
                    diagnostic_cost,
                    parse_q(conditional["cost"]),
                    names,
                    missing,
                    conditional,
                )
                if best is None or candidate[:4] < best[:4]:
                    best = candidate
        return None if best is None else (best[4], best[5])

    @staticmethod
    def diagnostic_policy(
        problem: Problem,
        missing: frozenset[str],
        router: "IndependentRouter",
    ) -> dict[str, object]:
        facts = tuple(sorted(missing))
        hypotheses = tuple(
            "".join(str(bit) for bit in bits)
            for bits in product((0, 1), repeat=len(facts))
        )
        values: dict[str, bool] = {}
        for hypothesis in hypotheses:
            true_facts = {
                name for name, bit in zip(facts, hypothesis) if bit == "1"
            }
            values[hypothesis] = router.shortest_portfolio(
                problem, extra_facts=true_facts
            ) is not None

        @lru_cache(maxsize=None)
        def solve(belief: tuple[str, ...]) -> tuple[Fraction, Fraction, dict[str, object]]:
            observed_values = {values[item] for item in belief}
            if len(observed_values) == 1:
                return Fraction(0), Fraction(0), {
                    "belief": list(belief),
                    "status": "TRUE" if True in observed_values else "FALSE",
                    "worst_cost": [0, 1],
                    "expected_cost": [0, 1],
                }
            candidates: list[tuple[Fraction, Fraction, str, dict[str, object]]] = []
            for index, fact in enumerate(facts):
                groups = {
                    bit: tuple(item for item in belief if item[index] == bit)
                    for bit in ("0", "1")
                }
                if not groups["0"] or not groups["1"]:
                    continue
                children: dict[str, dict[str, object]] = {}
                worst_children: list[Fraction] = []
                expected = DIAGNOSTIC_COSTS.get(fact, Fraction(5))
                for bit in ("0", "1"):
                    child_worst, child_expected, child = solve(groups[bit])
                    children[bit] = child
                    worst_children.append(child_worst)
                    expected += Fraction(len(groups[bit]), len(belief)) * child_expected
                worst = DIAGNOSTIC_COSTS.get(fact, Fraction(5)) + max(worst_children)
                node = {
                    "belief": list(belief),
                    "status": "UNKNOWN",
                    "experiment": f"verify:{fact}",
                    "experiment_cost": q(DIAGNOSTIC_COSTS.get(fact, Fraction(5))),
                    "worst_cost": q(worst),
                    "expected_cost": q(expected),
                    "children": children,
                }
                candidates.append((worst, expected, fact, node))
            if not candidates:
                return Fraction(0), Fraction(0), {
                    "belief": list(belief),
                    "status": "IMPOSSIBLE",
                    "worst_cost": [0, 1],
                    "expected_cost": [0, 1],
                }
            worst, expected, _fact, node = min(candidates)
            return worst, expected, node

        worst, expected, tree = solve(hypotheses)
        conflict_pairs = sum(
            values[left] != values[right]
            for left, right in combinations(hypotheses, 2)
        )
        fixed_cost = sum(
            (DIAGNOSTIC_COSTS.get(item, Fraction(5)) for item in facts),
            Fraction(0),
        )
        return {
            "status": "EXACT",
            "facts": list(facts),
            "hypotheses": len(hypotheses),
            "conflict_pairs": conflict_pairs,
            "fixed_basis": [f"verify:{item}" for item in facts],
            "fixed_cost": q(fixed_cost),
            "policy": {
                "exact": True,
                "worst_cost": q(worst),
                "expected_cost": q(expected),
                "tree": tree,
            },
        }

    def route(self, problem: Problem) -> dict[str, object]:
        contradictions = self.contradictions(problem.facts)
        if contradictions:
            return self.certificate(
                problem,
                "UNSAFE",
                "contradictory facts",
                contradictions=contradictions,
            )
        if not problem.outputs:
            return self.certificate(
                problem,
                "UNDERSPECIFIED",
                "the problem requests no statistical output",
            )
        if (
            "observational_twins" in problem.facts
            and "interventions_forbidden" in problem.facts
            and "identified_estimand" in problem.outputs
        ):
            return self.certificate(
                problem,
                "IMPOSSIBLE",
                "target-conflicting observational twins cannot be separated",
                witness=problem.witness
                or {"type": "observational_twins", "missing_experiment": "intervention"},
            )
        portfolio = self.shortest_portfolio(problem)
        if portfolio is not None:
            cost = parse_q(portfolio["cost"])
            if cost <= problem.budget:
                return self.certificate(
                    problem,
                    "SOLVED",
                    "minimum-cost verified capability portfolio found",
                    portfolio=portfolio,
                )
            return self.certificate(
                problem,
                "BUDGET_EXHAUSTED",
                "a complete portfolio exists but exceeds the declared budget",
                portfolio=portfolio,
                budget_shortfall=q(cost - problem.budget),
            )
        producible = set().union(*(item.provides for item in self.capabilities))
        unsupported = sorted(problem.outputs - set(problem.facts) - producible)
        if unsupported:
            return self.certificate(
                problem,
                "BLOCKED",
                "no registered capability can provide all requested outputs",
                unsupported_outputs=unsupported,
            )
        missing_result = self.minimal_missing(problem)
        if missing_result is None:
            return self.certificate(
                problem,
                "BLOCKED",
                "no composable portfolio exists in the registry",
            )
        missing, conditional = missing_result
        diagnostic = self.diagnostic_policy(problem, missing, self)
        return self.certificate(
            problem,
            "UNKNOWN",
            "a complete portfolio exists conditionally on unresolved facts",
            missing_facts=sorted(missing),
            conditional_portfolio=conditional,
            diagnostic_policy=diagnostic,
        )

    def certificate(
        self,
        problem: Problem,
        status: str,
        reason: str,
        **extra: object,
    ) -> dict[str, object]:
        payload = {
            "schema": "statistical-power-router-public/decision/1",
            "problem": problem.data(),
            "registry_sha256": self.registry_hash,
            "status": status,
            "reason": reason,
            **extra,
        }
        return {"payload": payload, "sha256": digest(payload)}

    def verify(self, certificate: Mapping[str, object]) -> list[str]:
        payload = certificate.get("payload")
        claimed = certificate.get("sha256")
        if not isinstance(payload, Mapping) or not isinstance(claimed, str):
            return ["certificate-shape"]
        if digest(payload) != claimed:
            return ["payload-hash"]
        if payload.get("registry_sha256") != self.registry_hash:
            return ["registry-drift"]
        problem_data = payload.get("problem")
        if not isinstance(problem_data, Mapping):
            return ["problem-shape"]
        rebuilt = self.route(Problem.from_data(problem_data))
        return [] if canonical(rebuilt["payload"]) == canonical(payload) else ["semantic-replay"]


def problem(
    name: str,
    goal: str,
    facts: Sequence[str],
    budget: int,
    *,
    requested: Sequence[str] = (),
    witness: Mapping[str, object] | None = None,
) -> Problem:
    return Problem(
        name=name,
        goal=goal,
        facts=frozenset(facts),
        budget=Fraction(budget),
        requested_outputs=frozenset(requested),
        witness=witness,
    )


def promotion_logic() -> dict[str, object]:
    gates = (
        ("typed_problem", Fraction(1), Fraction(19, 20)),
        ("registry_integrity", Fraction(2), Fraction(9, 10)),
        ("exact_composition", Fraction(3), Fraction(17, 20)),
        ("terminal_semantics", Fraction(5), Fraction(4, 5)),
        ("logic_power_diagnostics", Fraction(8), Fraction(3, 4)),
        ("budget_accounting", Fraction(13), Fraction(7, 10)),
        ("tamper_rejection", Fraction(21), Fraction(2, 3)),
        ("formal_boundary", Fraction(34), Fraction(3, 5)),
    )
    hypotheses = tuple(
        "".join(str(bit) for bit in bits)
        for bits in product((0, 1), repeat=len(gates))
    )
    prior: dict[str, Fraction] = {}
    for hypothesis in hypotheses:
        weight = Fraction(1)
        for bit, (_name, _cost, clean) in zip(hypothesis, gates):
            weight *= clean if bit == "0" else 1 - clean
        prior[hypothesis] = weight

    @lru_cache(maxsize=None)
    def solve(belief: tuple[str, ...], remaining: tuple[int, ...]) -> tuple[Fraction, Fraction, dict[str, object]]:
        if all(item == "0" * len(gates) for item in belief):
            return Fraction(0), Fraction(0), {"belief": list(belief), "status": "TRUE"}
        if all(item != "0" * len(gates) for item in belief):
            return Fraction(0), Fraction(0), {"belief": list(belief), "status": "FALSE"}
        candidates = []
        belief_mass = sum((prior[item] for item in belief), Fraction(0))
        for index in remaining:
            groups = {
                bit: tuple(item for item in belief if item[index] == bit)
                for bit in ("0", "1")
            }
            if not groups["0"] or not groups["1"]:
                continue
            next_remaining = tuple(item for item in remaining if item != index)
            children = {}
            expected = gates[index][1]
            worst_children = []
            for bit in ("0", "1"):
                child_worst, child_expected, child = solve(groups[bit], next_remaining)
                children[bit] = child
                worst_children.append(child_worst)
                group_mass = sum((prior[item] for item in groups[bit]), Fraction(0))
                expected += group_mass / belief_mass * child_expected
            worst = gates[index][1] + max(worst_children)
            candidates.append((worst, expected, gates[index][0], index, children))
        if not candidates:
            raise AssertionError("promotion problem became undecidable")
        worst, expected, name, index, children = min(candidates)
        return worst, expected, {
            "belief": list(belief),
            "status": "UNKNOWN",
            "experiment": name,
            "worst_cost": q(worst),
            "expected_cost": q(expected),
            "children": children,
        }

    worst, expected, tree = solve(hypotheses, tuple(range(len(gates))))
    clean_path = []
    node = tree
    while node.get("status") == "UNKNOWN":
        clean_path.append(node["experiment"])
        node = node["children"]["0"]
    return {
        "hypotheses": len(hypotheses),
        "conflict_pairs": len(hypotheses) - 1,
        "fixed_cost": q(sum((item[1] for item in gates), Fraction(0))),
        "worst_cost": q(worst),
        "expected_cost": q(expected),
        "clean_path": clean_path,
    }


def build_payload() -> dict[str, object]:
    router = IndependentRouter()
    controls = {
        "causal_composition": router.route(
            problem(
                "causal-composition",
                "causal_effect",
                ("causal", "finite", "graph_known", "crossfit_provenance", "overlap"),
                18,
            )
        ),
        "active_evidence": router.route(
            problem(
                "active-evidence",
                "active_evidence",
                ("finite", "world_family", "experiments_declared", "costs_declared"),
                12,
            )
        ),
        "diagnostic_unknown": router.route(
            problem("diagnostic-unknown", "lower_bound", ("finite",), 10)
        ),
        "budget_exhausted": router.route(
            problem(
                "budget-exhausted",
                "lower_bound",
                ("finite", "rational", "laws_known"),
                5,
            )
        ),
        "impossible": router.route(
            problem(
                "impossible",
                "causal_effect",
                (
                    "causal",
                    "finite",
                    "graph_known",
                    "observational_twins",
                    "interventions_forbidden",
                ),
                100,
                witness={"left": "w0", "right": "w1"},
            )
        ),
        "unsafe": router.route(
            problem(
                "unsafe",
                "causal_bounds",
                ("finite", "world_family", "graph_known", "graph_unknown"),
                100,
            )
        ),
        "blocked": router.route(
            problem(
                "blocked",
                "custom",
                ("finite",),
                100,
                requested=("quantum_oracle",),
            )
        ),
        "sequential": router.route(
            problem(
                "sequential",
                "sequential_monitoring",
                ("sequential", "bounded_score", "predictable_strategy"),
                8,
            )
        ),
        "full_inference": router.route(
            problem(
                "full-inference",
                "full_inference",
                (
                    "causal",
                    "finite",
                    "graph_known",
                    "crossfit_provenance",
                    "overlap",
                    "rational",
                    "laws_known",
                ),
                28,
            )
        ),
    }
    expected = {
        "causal_composition": "SOLVED",
        "active_evidence": "SOLVED",
        "diagnostic_unknown": "UNKNOWN",
        "budget_exhausted": "BUDGET_EXHAUSTED",
        "impossible": "IMPOSSIBLE",
        "unsafe": "UNSAFE",
        "blocked": "BLOCKED",
        "sequential": "SOLVED",
        "full_inference": "SOLVED",
    }
    for name, status in expected.items():
        if controls[name]["payload"]["status"] != status:
            raise AssertionError(f"{name} status changed")
        if router.verify(controls[name]):
            raise AssertionError(f"{name} semantic replay failed")

    causal = controls["causal_composition"]["payload"]["portfolio"]
    if causal["capabilities"] != ["finite_causal_id", "crossfit_finite"]:
        raise AssertionError(f"causal portfolio changed: {causal}")
    if causal["cost"] != [18, 1]:
        raise AssertionError("causal portfolio cost changed")
    active = controls["active_evidence"]["payload"]["portfolio"]
    if active["capabilities"] != ["epistemic_policy"]:
        raise AssertionError("active evidence portfolio changed")
    diagnostic = controls["diagnostic_unknown"]["payload"]["diagnostic_policy"]
    if diagnostic["facts"] != ["laws_known", "rational"]:
        raise AssertionError(f"diagnostic facts changed: {diagnostic}")
    if diagnostic["fixed_cost"] != [6, 1]:
        raise AssertionError("diagnostic fixed cost changed")
    if diagnostic["policy"]["worst_cost"] != [6, 1]:
        raise AssertionError("diagnostic worst cost changed")
    if diagnostic["policy"]["expected_cost"] != [7, 2]:
        raise AssertionError("diagnostic expected cost changed")
    full = controls["full_inference"]["payload"]["portfolio"]
    if set(full["capabilities"]) != {
        "finite_causal_id",
        "crossfit_finite",
        "lower_bound_metacompiler",
    }:
        raise AssertionError(f"full inference portfolio changed: {full}")
    if full["cost"] != [28, 1]:
        raise AssertionError("full inference cost changed")

    tampered = deepcopy(controls["causal_composition"])
    tampered["payload"]["status"] = "BLOCKED"
    if router.verify(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")
    forged = deepcopy(tampered)
    forged["sha256"] = digest(forged["payload"])
    if router.verify(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")

    logic = promotion_logic()
    if logic["hypotheses"] != 256 or logic["conflict_pairs"] != 255:
        raise AssertionError("promotion hypothesis counts changed")
    if logic["fixed_cost"] != [87, 1] or logic["worst_cost"] != [87, 1]:
        raise AssertionError("promotion costs changed")
    if len(logic["clean_path"]) != 8:
        raise AssertionError("promotion clean path is incomplete")

    return {
        "schema": "statistical-power-router-public/report/1",
        "status": "SOLVED",
        "comparison_target": PRIVATE_BINDING,
        "registry_size": len(router.capabilities),
        "registry_sha256": router.registry_hash,
        "goals_supported": sorted(item for item in GOAL_OUTPUTS if item != "custom"),
        "terminal_statuses": list(TERMINALS),
        "controls": {
            name: {
                "status": certificate["payload"]["status"],
                "certificate_sha256": certificate["sha256"],
                "portfolio": certificate["payload"].get("portfolio"),
                "missing_facts": certificate["payload"].get("missing_facts"),
                "diagnostic_policy": certificate["payload"].get("diagnostic_policy"),
            }
            for name, certificate in controls.items()
        },
        "logic_power_v10_independent_reconstruction": logic,
        "negative_controls": {
            "contradictory_facts": "UNSAFE",
            "observational_twins": "IMPOSSIBLE",
            "insufficient_budget": "BUDGET_EXHAUSTED",
            "unsupported_output": "BLOCKED",
            "missing_conditions": "UNKNOWN",
            "payload_tamper": "REJECTED:payload-hash",
            "semantic_forgery": "REJECTED:semantic-replay",
        },
        "independent_algorithm": (
            "Dijkstra search over fact-closure states; private implementation "
            "uses exact subset enumeration."
        ),
        "scientific_boundary": (
            "Exact for the declared finite registry and typed fact grammar. "
            "The capsule verifies composition and routing, not execution of every "
            "downstream adapter on arbitrary raw datasets."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = build_payload()
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload = certificate.get("payload")
    claimed = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ["certificate-shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    rebuilt = build_certificate()
    return [] if canonical(rebuilt["payload"]) == canonical(payload) else ["semantic-replay"]


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public router certificate failed self replay")
    tampered = deepcopy(certificate)
    tampered["payload"]["status"] = "BLOCKED"
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("public payload tamper accepted")
    forged = deepcopy(tampered)
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("public semantic forgery accepted")

    report = {
        "schema": "statistical-power-router-public/summary/1",
        **certificate["payload"],
        "semantic_certificate": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
    }
    report["report_sha256"] = digest(report)
    write(ROOT / "POWER_ROUTER_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "POWER_ROUTER_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
