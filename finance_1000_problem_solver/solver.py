"""Independent public replay of the Finance 1000 Logic Power Problem Solver case.

This capsule reconstructs the relevant typed Problem IR, fail-closed router,
robust minimax decision, strict gate score, and terminal certificate using only
the Python standard library.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping


PRIVATE_GIT_BLOB_BINDINGS = {
    "certificate.py": "69a7e8203d37564636e36f1c27a6b6c46b499627",
    "decision.py": "c2e9d390ea81a9c6c08978f91ac9f0cd92526427",
    "finance_1000.py": "c9c97ce965513bc03a846d58ae14b17f76d20833",
    "problem_ir.py": "9f51b18e48711458dd8c65289d31dbdba8a7ecbd",
    "router.py": "96da56fa3f9382cc48bec7377b58eb0e9ed83dcc",
    "solver_registry.py": "b032aa3fc82b73461c3a9092d1e9fe5c60e4aaa9",
}


class ConditionKind(str, Enum):
    FACT = "FACT"
    GOAL = "GOAL"
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    SOFT_PREFERENCE = "SOFT_PREFERENCE"
    SAFETY_INVARIANT = "SAFETY_INVARIANT"
    BUDGET = "BUDGET"
    EVIDENCE_REQUIREMENT = "EVIDENCE_REQUIREMENT"


class TerminalStatus(str, Enum):
    SOLVED = "SOLVED"
    IMPOSSIBLE = "IMPOSSIBLE"
    BLOCKED = "BLOCKED"
    UNDERSPECIFIED = "UNDERSPECIFIED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    UNSAFE = "UNSAFE"


class Horizon(str, Enum):
    STATIC = "STATIC"
    FINITE = "FINITE"
    INFINITE_DISCOUNTED = "INFINITE_DISCOUNTED"
    RECEDING = "RECEDING"


class UncertaintyKind(str, Enum):
    NONE = "NONE"
    PROBABILISTIC = "PROBABILISTIC"
    INTERVAL = "INTERVAL"
    ADVERSARIAL = "ADVERSARIAL"
    UNKNOWN = "UNKNOWN"


class ModelStatus(str, Enum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    SIMULATOR = "SIMULATOR"
    LEARNABLE = "LEARNABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Condition:
    name: str
    kind: ConditionKind
    expression: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def canonical_data(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "expression": self.expression,
            "metadata": normalize_json(self.metadata),
        }


@dataclass(frozen=True)
class SearchBudget:
    rollouts: int = 0
    max_depth: int = 0
    time_ms: int = 0
    memory_mb: int = 0

    def canonical_data(self) -> dict[str, int]:
        return {
            "rollouts": self.rollouts,
            "max_depth": self.max_depth,
            "time_ms": self.time_ms,
            "memory_mb": self.memory_mb,
        }


@dataclass(frozen=True)
class ProblemIR:
    problem_id: str
    states: tuple[str, ...]
    initial_belief: tuple[str, ...]
    goal: str
    conditions: tuple[Condition, ...]
    actions: tuple[str, ...]
    experiments: tuple[str, ...]
    agents: tuple[str, ...]
    horizon: Horizon
    uncertainty: UncertaintyKind
    model_status: ModelStatus
    objective: str
    capabilities: tuple[str, ...]
    verifiers: tuple[str, ...]
    search_budget: SearchBudget = field(default_factory=SearchBudget)
    solution_concept: str | None = None
    schema: str = "logic-power-problem-ir/1"

    def canonical_data(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "problem_id": self.problem_id,
            "states": sorted(self.states),
            "initial_belief": sorted(self.initial_belief),
            "goal": self.goal,
            "conditions": [
                item.canonical_data()
                for item in sorted(
                    self.conditions,
                    key=lambda value: (value.name, value.kind.value, value.expression),
                )
            ],
            "actions": sorted(self.actions),
            "experiments": sorted(self.experiments),
            "agents": sorted(self.agents),
            "horizon": self.horizon.value,
            "uncertainty": self.uncertainty.value,
            "model_status": self.model_status.value,
            "objective": self.objective,
            "capabilities": sorted(self.capabilities),
            "verifiers": sorted(self.verifiers),
            "search_budget": self.search_budget.canonical_data(),
            "solution_concept": self.solution_concept,
        }

    def fingerprint(self) -> str:
        return digest(self.canonical_data())


@dataclass(frozen=True)
class RoutingDecision:
    problem_classes: tuple[str, ...]
    selected_solver: str | None
    eligible_solvers: tuple[str, ...]
    rejected_solvers: dict[str, tuple[str, ...]]
    trace: tuple[str, ...]

    def canonical_data(self) -> dict[str, Any]:
        return {
            "problem_classes": list(self.problem_classes),
            "selected_solver": self.selected_solver,
            "eligible_solvers": list(self.eligible_solvers),
            "rejected_solvers": {
                key: list(self.rejected_solvers[key])
                for key in sorted(self.rejected_solvers)
            },
            "trace": list(self.trace),
        }

    def fingerprint(self) -> str:
        return digest(self.canonical_data())


@dataclass(frozen=True)
class DecisionResult:
    action: str
    score: Fraction
    scores: Mapping[str, Fraction]
    criterion: str


def normalize_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): normalize_json(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(type(value).__name__)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def classify_problem(problem: ProblemIR) -> tuple[tuple[str, ...], tuple[str, ...]]:
    classes: set[str] = set()
    trace: list[str] = []
    if len(problem.agents) > 1:
        classes.add("GAME")
        trace.append("multiple agents => GAME")
    if problem.actions and problem.horizon is not Horizon.STATIC:
        classes.add("PLANNING")
        trace.append("actions plus non-static horizon => PLANNING")
    if problem.uncertainty is not UncertaintyKind.NONE:
        classes.add("DECISION")
        trace.append(f"uncertainty={problem.uncertainty.value} => DECISION")
    if problem.model_status is ModelStatus.SIMULATOR and problem.search_budget.rollouts > 0:
        classes.add("SIMULATION_SEARCH")
        trace.append("simulator plus rollouts => SIMULATION_SEARCH")
    if problem.model_status is ModelStatus.LEARNABLE:
        classes.add("LEARNING")
        trace.append("learnable dynamics => LEARNING")
    if problem.experiments:
        classes.add("ACTIVE_INFORMATION")
        trace.append("declared experiments => ACTIVE_INFORMATION")
    if any(item.kind is ConditionKind.EVIDENCE_REQUIREMENT for item in problem.conditions):
        classes.add("VERIFICATION")
        trace.append("evidence requirement => VERIFICATION")
    if not classes or classes == {"VERIFICATION"}:
        classes.add("DEDUCTION")
        trace.append("no sequential, strategic, or stochastic structure => DEDUCTION")
    return tuple(sorted(classes)), tuple(trace)


def route_problem(problem: ProblemIR) -> RoutingDecision:
    classes, trace = classify_problem(problem)
    available = set(problem.capabilities)
    eligible: list[str] = []
    rejected: dict[str, tuple[str, ...]] = {}

    if "logic_exact" in available:
        eligible.append("logic_exact")
    if "robust_minimax_regret" in available:
        if problem.uncertainty in {
            UncertaintyKind.INTERVAL,
            UncertaintyKind.ADVERSARIAL,
            UncertaintyKind.UNKNOWN,
        }:
            eligible.append("robust_minimax_regret")
        else:
            rejected["robust_minimax_regret"] = ("robust_uncertainty",)
    if "monte_carlo_evaluation" in available:
        reasons: list[str] = []
        if problem.search_budget.rollouts <= 0:
            reasons.append("positive_rollout_budget")
        if problem.uncertainty is UncertaintyKind.NONE and problem.model_status is not ModelStatus.SIMULATOR:
            reasons.append("stochastic_source_or_simulator")
        if reasons:
            rejected["monte_carlo_evaluation"] = tuple(reasons)
        else:
            eligible.append("monte_carlo_evaluation")
    if "finite_dynamic_programming" in available:
        reasons = []
        if "PLANNING" not in classes:
            reasons.append("planning_structure")
        if problem.horizon is not Horizon.FINITE:
            reasons.append("finite_horizon")
        if problem.model_status is not ModelStatus.KNOWN:
            reasons.append("known_transition_model")
        if reasons:
            rejected["finite_dynamic_programming"] = tuple(reasons)
        else:
            eligible.append("finite_dynamic_programming")

    order = (
        "finite_dynamic_programming",
        "robust_minimax_regret",
        "logic_exact",
        "monte_carlo_evaluation",
    )
    selected = next((name for name in order if name in eligible), None)
    routed_trace = list(trace)
    routed_trace.append(f"selected={selected}")
    for name in sorted(rejected):
        routed_trace.append(f"rejected={name}:{','.join(rejected[name])}")
    return RoutingDecision(
        problem_classes=classes,
        selected_solver=selected,
        eligible_solvers=tuple(sorted(eligible)),
        rejected_solvers=rejected,
        trace=tuple(routed_trace),
    )


def minimax_regret_decision(
    utilities: Mapping[str, Mapping[str, Fraction]],
) -> DecisionResult:
    actions = tuple(sorted(utilities))
    states = tuple(sorted(utilities[actions[0]]))
    best = {state: max(utilities[action][state] for action in actions) for state in states}
    regrets = {
        action: max(best[state] - utilities[action][state] for state in states)
        for action in actions
    }
    action = min(actions, key=lambda name: (regrets[name], name))
    return DecisionResult(action, regrets[action], regrets, "minimax_regret")


GATE_WEIGHTS = {
    "G00": 110,
    "G01": 100,
    "G02": 100,
    "G03": 110,
    "G04": 100,
    "G05": 120,
    "G06": 100,
    "G07": 100,
    "G08": 80,
    "G09": 80,
}
GATE_STATUS = {
    "G00": "PASS",
    "G01": "PASS",
    "G02": "PASS",
    "G03": "PASS",
    "G04": "PASS",
    "G05": "PASS",
    "G06": "PASS",
    "G07": "OPEN",
    "G08": "PASS",
    "G09": "OPEN",
}
WORLD_STATES = (
    "both_gates_closable",
    "only_g07_closable",
    "only_g09_closable",
    "neither_gate_closable_under_current_claim",
)


def strict_score() -> int:
    assert sum(GATE_WEIGHTS.values()) == 1000
    return sum(GATE_WEIGHTS[key] for key in GATE_WEIGHTS if GATE_STATUS[key] == "PASS")


def build_problem() -> ProblemIR:
    return ProblemIR(
        problem_id="finance-god-level-1000",
        states=WORLD_STATES,
        initial_belief=WORLD_STATES,
        goal="all finance gates G00 through G09 are independently evidenced PASS",
        conditions=(
            Condition("verified_base", ConditionKind.FACT, "G00-G06 and G08 have canonical PASS evidence", {"score": strict_score()}),
            Condition("utility_gate", ConditionKind.GOAL, "G07 requires measured prospective economic or institutional utility", {"weight": 100}),
            Condition("discovery_gate", ConditionKind.GOAL, "G09 requires a new falsifiable claim bounded by prior art and independently replicated", {"weight": 80}),
            Condition("no_score_inflation", ConditionKind.SAFETY_INVARIANT, "no gate receives points without its declared evidence"),
            Condition("no_false_promotion", ConditionKind.SAFETY_INVARIANT, "no unsupported financial attribution may be promoted"),
            Condition("sealed_evaluation", ConditionKind.HARD_CONSTRAINT, "holdouts, baselines and claims are frozen before outcome inspection"),
            Condition("zero_paid_infrastructure", ConditionKind.BUDGET, "paid spend equals zero"),
            Condition("independent_replay", ConditionKind.EVIDENCE_REQUIREMENT, "a clean independent replay must reproduce decisions and hashes"),
            Condition("priority_boundary", ConditionKind.EVIDENCE_REQUIREMENT, "G09 must survive systematic primary-literature comparison and independent replication"),
        ),
        actions=(
            "finish_g07_strong_baseline_and_clean_replay",
            "finish_g09_prior_art_and_independent_replication",
            "parallel_g07_g09_program",
            "more_internal_theory",
        ),
        experiments=(
            "stage2_strong_baseline_documentary_holdout",
            "clean_independent_replay",
            "systematic_prior_art_search",
            "cross_domain_replication",
        ),
        agents=("finance_meta_controller",),
        horizon=Horizon.FINITE,
        uncertainty=UncertaintyKind.UNKNOWN,
        model_status=ModelStatus.PARTIAL,
        objective="maximize independently resolved weighted gates while minimizing unsupported promotions, evidence cost and leakage",
        capabilities=("finite_dynamic_programming", "robust_minimax_regret", "logic_exact", "monte_carlo_evaluation"),
        verifiers=("python", "node", "github_actions", "notion_evidence_ledger"),
        search_budget=SearchBudget(rollouts=10000, max_depth=4),
        solution_concept="robust minimum-regret evidence program",
    )


def planning_utilities() -> dict[str, dict[str, Fraction]]:
    values = {
        "finish_g07_strong_baseline_and_clean_replay": Fraction(80),
        "finish_g09_prior_art_and_independent_replication": Fraction(60),
        "parallel_g07_g09_program": Fraction(150),
        "more_internal_theory": Fraction(-5),
    }
    return {action: {state: value for state in WORLD_STATES} for action, value in values.items()}


def build_report() -> dict[str, Any]:
    problem = build_problem()
    route = route_problem(problem)
    decision = minimax_regret_decision(planning_utilities())
    score = strict_score()
    open_gates = [gate for gate in GATE_WEIGHTS if GATE_STATUS[gate] != "PASS"]
    result = {
        "strict_score": score,
        "maximum_score": 1000,
        "open_points": 1000 - score,
        "gate_status": GATE_STATUS,
        "open_gates": open_gates,
        "selected_method": route.selected_solver,
        "selected_action_portfolio": decision.action,
        "maximum_claim": "advanced_finance_system_with_real_evidence_program_in_progress",
    }
    evidence = {
        "private_git_blob_bindings": PRIVATE_GIT_BLOB_BINDINGS,
        "gate_weights": GATE_WEIGHTS,
        "routing": route.canonical_data(),
        "planning_criterion": decision.criterion,
        "planning_regret": [decision.score.numerator, decision.score.denominator],
        "planning_scores": {
            action: [value.numerator, value.denominator]
            for action, value in sorted(decision.scores.items())
        },
        "boundary": "planning units select work; only independently evidenced gate PASS changes the score",
    }
    payload = {
        "problem_fingerprint": problem.fingerprint(),
        "routing_fingerprint": route.fingerprint(),
        "status": TerminalStatus.BLOCKED.value,
        "result": result,
        "evidence": evidence,
    }
    certificate = {
        "schema": "logic-power-problem-solver/certificate/1",
        "payload": payload,
        "payload_sha256": digest(payload),
    }
    report = {
        "schema": "finance-1000-logic-power-solver/public-replay/1",
        "problem_ir": problem.canonical_data(),
        "routing": route.canonical_data(),
        "result": result,
        "certificate": certificate,
    }
    report["report_sha256"] = digest(report)
    return report


def verify_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    certificate = report.get("certificate")
    if not isinstance(certificate, Mapping):
        return ["certificate"]
    payload = certificate.get("payload")
    if not isinstance(payload, Mapping):
        return ["payload"]
    if certificate.get("payload_sha256") != digest(payload):
        errors.append("payload-hash")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return errors + ["result"]
    expected_score = strict_score()
    if result.get("strict_score") != expected_score:
        errors.append("strict-score")
    if result.get("open_gates") != ["G07", "G09"]:
        errors.append("open-gates")
    if result.get("open_points") != 180:
        errors.append("open-points")
    if result.get("selected_method") != "robust_minimax_regret":
        errors.append("selected-method")
    if result.get("selected_action_portfolio") != "parallel_g07_g09_program":
        errors.append("selected-action")
    routing = report.get("routing")
    if not isinstance(routing, Mapping) or routing.get("selected_solver") != "robust_minimax_regret":
        errors.append("routing")
    if report.get("report_sha256") != digest({key: report[key] for key in report if key != "report_sha256"}):
        errors.append("report-hash")
    return errors


def main() -> int:
    output = Path("reports/finance_1000_problem_solver")
    output.mkdir(parents=True, exist_ok=True)
    report = build_report()
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = verify_report(report)
    if errors:
        raise SystemExit(f"verification failed: {errors}")
    print(json.dumps({
        "score": report["result"]["strict_score"],
        "open_gates": report["result"]["open_gates"],
        "selected_method": report["result"]["selected_method"],
        "selected_action": report["result"]["selected_action_portfolio"],
        "certificate_sha256": report["certificate"]["payload_sha256"],
        "report_sha256": report["report_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
