from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
from typing import Mapping, Sequence

from verify_statistical_power_router_public import (
    IndependentRouter,
    Problem,
    canonical,
    digest,
    q,
)

ROOT = Path(__file__).resolve().parent

PRIVATE_BINDING = {
    "repository": "cristh99/my_first_repository",
    "pull_request": 109,
    "head": "0ec1abdbe53b67c12a391f1e834028133439fc98",
    "git_blobs": {
        "orchestrator": "b709d5a4037ecff6befe02a7dcacfd9811cabf40",
        "runner": "b637fb00862747f6a5601df2006508bcc0824dce",
        "tests": "0829b76087b628d5b6e4475526162db56b8789d0",
        "lean": "4a156ff7aa89767a2dea7110eafe53e21e5100c1",
        "workflow": "71d352a558783dc71e5f1b2390716c7cc6a5d6c0",
    },
}


def parse_q(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("rational must be [numerator, denominator]")
    numerator, denominator = value
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        raise ValueError("rational entries must be integers")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return Fraction(numerator, denominator)


def adapter_certificate(kind: str, payload: Mapping[str, object]) -> dict[str, object]:
    value = {"schema": f"execution-orchestrator-public/{kind}/1", **dict(payload)}
    return {"payload": value, "sha256": digest(value)}


def execute_causal_id(data: Mapping[str, object]) -> dict[str, object]:
    graph = data.get("graph")
    outcomes = data.get("outcomes")
    interventions = data.get("interventions")
    if (
        not isinstance(graph, Mapping)
        or outcomes != ["Y"]
        or interventions != ["X"]
        or graph.get("nodes") != ["X", "Y"]
        or graph.get("directed") != [["X", "Y"]]
    ):
        raise ValueError("public causal control expects X -> Y")
    bidirected = graph.get("bidirected")
    if bidirected == [["X", "Y"]]:
        certificate = adapter_certificate(
            "causal-id",
            {
                "status": "NOT_IDENTIFIABLE",
                "graph": graph,
                "hedge": {
                    "forest": ["X", "Y"],
                    "subforest": ["Y"],
                    "roots": ["Y"],
                },
            },
        )
        return {
            "status": "IMPOSSIBLE",
            "provides": ["formal_certificate", "impossibility_witness"],
            "certificate": certificate,
            "summary": {"hedge": certificate["payload"]["hedge"]},
            "reason": "bow graph has an explicit hedge obstruction",
        }
    if bidirected != []:
        raise ValueError("unexpected bidirected control")
    certificate = adapter_certificate(
        "causal-id",
        {
            "status": "IDENTIFIED",
            "graph": graph,
            "expression": "P(Y|X)",
            "rule": "truncated factorization for X -> Y",
        },
    )
    return {
        "status": "SOLVED",
        "provides": ["formal_certificate", "identified_estimand"],
        "certificate": certificate,
        "summary": {"identified_expression": "P(Y|X)", "trace_steps": 1},
        "reason": None,
    }


def lower_problem() -> tuple[tuple[str, ...], dict[str, tuple[Fraction, Fraction]], dict[str, Fraction]]:
    worlds = ("w0", "w1", "w2", "w3", "w4")
    laws = {
        "w0": (Fraction(9, 10), Fraction(1, 10)),
        "w1": (Fraction(7, 10), Fraction(3, 10)),
        "w2": (Fraction(1, 2), Fraction(1, 2)),
        "w3": (Fraction(3, 10), Fraction(7, 10)),
        "w4": (Fraction(1, 10), Fraction(9, 10)),
    }
    targets = {
        "w0": Fraction(0),
        "w1": Fraction(1, 4),
        "w2": Fraction(1, 2),
        "w3": Fraction(3, 4),
        "w4": Fraction(1),
    }
    return worlds, laws, targets


def bayes_error(
    subset: Sequence[str], laws: Mapping[str, tuple[Fraction, Fraction]]
) -> Fraction:
    success = Fraction(0)
    for outcome in range(2):
        success += Fraction(1, len(subset)) * max(
            laws[world][outcome] for world in subset
        )
    return 1 - success


def execute_lower_bound(_data: Mapping[str, object]) -> dict[str, object]:
    worlds, laws, targets = lower_problem()
    le_cam_best: tuple[Fraction, tuple[str, str]] | None = None
    for left, right in combinations(worlds, 2):
        separation = (targets[left] - targets[right]) ** 2
        tv = sum(
            abs(laws[left][index] - laws[right][index])
            for index in range(2)
        ) / 2
        bound = separation * (1 - tv) / 8
        candidate = (bound, (left, right))
        if le_cam_best is None or candidate > le_cam_best:
            le_cam_best = candidate
    assert le_cam_best is not None

    packing_best: tuple[Fraction, tuple[str, ...], Fraction, Fraction] | None = None
    packings_examined = 0
    for size in range(2, len(worlds) + 1):
        for subset in combinations(worlds, size):
            packings_examined += 1
            separation = min(
                (targets[left] - targets[right]) ** 2
                for left, right in combinations(subset, 2)
            )
            error = bayes_error(subset, laws)
            bound = separation / 4 * error
            candidate = (bound, subset, separation, error)
            if packing_best is None or candidate > packing_best:
                packing_best = candidate
    assert packing_best is not None
    if packing_best[0] != Fraction(9, 320):
        raise AssertionError(f"packing lower bound changed: {packing_best}")
    if le_cam_best[0] != Fraction(1, 40):
        raise AssertionError(f"Le Cam lower bound changed: {le_cam_best}")

    certificate = adapter_certificate(
        "lower-bound",
        {
            "status": "SOLVED",
            "selected_method": "exact_finite_packing",
            "selected_lower_bound": q(packing_best[0]),
            "selected_subset": list(packing_best[1]),
            "minimum_squared_separation": q(packing_best[2]),
            "testing_error": q(packing_best[3]),
            "packings_examined": packings_examined,
            "le_cam_lower_bound": q(le_cam_best[0]),
            "le_cam_pair": list(le_cam_best[1]),
        },
    )
    return {
        "status": "SOLVED",
        "provides": ["formal_certificate", "lower_bound", "optimality"],
        "certificate": certificate,
        "summary": {
            "selected_method": "exact_finite_packing",
            "selected_lower_bound": q(packing_best[0]),
            "candidate_upper_bound": None,
            "verdict": "LOWER_BOUND",
            "work_units": packings_examined,
        },
        "reason": None,
    }


def exact_rows(*, leak: bool = False) -> tuple[list[dict[str, object]], dict[str, list[str]]]:
    rows: list[dict[str, object]] = []
    counter = 0
    patterns = {
        ("z0", 0): (0, 0, 0, 0),
        ("z0", 1): (0, 0, 1, 1),
        ("z1", 0): (0, 0, 0, 1),
        ("z1", 1): (0, 1, 1, 1),
    }
    for fold in ("f0", "f1"):
        for (z_value, action), outcomes in patterns.items():
            for outcome in outcomes:
                rows.append(
                    {
                        "row_id": f"r{counter:02d}",
                        "fold": fold,
                        "z": z_value,
                        "a": action,
                        "y": outcome,
                    }
                )
                counter += 1
    training = {
        "f0": [row["row_id"] for row in rows if row["fold"] == "f1"],
        "f1": [row["row_id"] for row in rows if row["fold"] == "f0"],
    }
    if leak:
        training["f0"].append(
            next(row["row_id"] for row in rows if row["fold"] == "f0")
        )
    return rows, training


def fit_nuisance(rows: Sequence[Mapping[str, object]]) -> dict[str, tuple[Fraction, Fraction, Fraction]]:
    result = {}
    for z_value in ("z0", "z1"):
        z_rows = [row for row in rows if row["z"] == z_value]
        propensity = Fraction(sum(int(row["a"]) for row in z_rows), len(z_rows))
        means = []
        for action in (0, 1):
            cell = [row for row in z_rows if row["a"] == action]
            means.append(Fraction(sum(int(row["y"]) for row in cell), len(cell)))
        result[z_value] = (propensity, means[0], means[1])
    return result


def execute_crossfit(data: Mapping[str, object]) -> dict[str, object]:
    leak = str(data.get("case", "")).startswith("leaky")
    rows, training = exact_rows(leak=leak)
    fold_of = {str(row["row_id"]): str(row["fold"]) for row in rows}
    for fold, identifiers in training.items():
        for row_id in identifiers:
            if fold_of[row_id] == fold:
                certificate = adapter_certificate(
                    "crossfit",
                    {
                        "status": "INVALID_LEAKAGE",
                        "witness": {
                            "fold": fold,
                            "held_out_row_in_training": row_id,
                        },
                    },
                )
                return {
                    "status": "UNSAFE",
                    "provides": ["formal_certificate"],
                    "certificate": certificate,
                    "summary": {"failure": certificate["payload"]},
                    "reason": "held-out row appears in its own training set",
                }

    scores: list[Fraction] = []
    fold_packets = {}
    for fold in ("f0", "f1"):
        train = [row for row in rows if row["row_id"] in set(training[fold])]
        nuisance = fit_nuisance(train)
        held_out = [row for row in rows if row["fold"] == fold]
        fold_packets[fold] = {
            "training_count": len(train),
            "held_out_count": len(held_out),
        }
        for row in held_out:
            propensity, mu0, mu1 = nuisance[str(row["z"])]
            action = int(row["a"])
            outcome = int(row["y"])
            score = (
                mu1
                - mu0
                + Fraction(action, 1) / propensity * (outcome - mu1)
                - Fraction(1 - action, 1) / (1 - propensity) * (outcome - mu0)
            )
            scores.append(score)
    estimate = sum(scores, Fraction(0)) / len(scores)
    influences = [score - estimate for score in scores]
    variance = sum((value * value for value in influences), Fraction(0)) / len(influences)
    if estimate != Fraction(1, 2) or variance != Fraction(5, 8):
        raise AssertionError("cross-fit control changed")
    certificate = adapter_certificate(
        "crossfit",
        {
            "status": "SOLVED",
            "estimate": q(estimate),
            "empirical_variance": q(variance),
            "score_count": len(scores),
            "folds": fold_packets,
        },
    )
    return {
        "status": "SOLVED",
        "provides": ["formal_certificate", "point_estimate", "uncertainty"],
        "certificate": certificate,
        "summary": {
            "estimate": q(estimate),
            "empirical_variance": q(variance),
            "product_rate": {"status": "PASS"},
            "folds": ["f0", "f1"],
        },
        "reason": None,
    }


def solve_square(matrix: Sequence[Sequence[Fraction]], rhs: Sequence[Fraction]) -> list[Fraction] | None:
    dimension = len(matrix)
    augmented = [list(row) + [rhs[index]] for index, row in enumerate(matrix)]
    pivot_row = 0
    for column in range(dimension):
        pivot = next(
            (row for row in range(pivot_row, dimension) if augmented[row][column] != 0),
            None,
        )
        if pivot is None:
            return None
        augmented[pivot_row], augmented[pivot] = augmented[pivot], augmented[pivot_row]
        value = augmented[pivot_row][column]
        augmented[pivot_row] = [item / value for item in augmented[pivot_row]]
        for row in range(dimension):
            if row == pivot_row or augmented[row][column] == 0:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index] - factor * augmented[pivot_row][index]
                for index in range(dimension + 1)
            ]
        pivot_row += 1
    return [augmented[index][-1] for index in range(dimension)]


def synthesize_factor(laws: Mapping[str, tuple[Fraction, Fraction]]) -> tuple[Fraction, Fraction]:
    rows = [
        ((Fraction(1), Fraction(0), Fraction(0)), Fraction(0)),
        ((Fraction(0), Fraction(1), Fraction(0)), Fraction(0)),
    ]
    for world in ("null_a", "null_b"):
        rows.append((laws[world] + (Fraction(0),), Fraction(1)))
    for world in ("alt_a", "alt_b"):
        rows.append((laws[world] + (Fraction(-1),), Fraction(0)))
    best: tuple[Fraction, tuple[Fraction, Fraction]] | None = None
    for active in combinations(range(len(rows)), 3):
        solution = solve_square(
            [rows[index][0] for index in active],
            [rows[index][1] for index in active],
        )
        if solution is None:
            continue
        factor = (solution[0], solution[1])
        gamma = solution[2]
        if any(value < 0 for value in factor):
            continue
        null_means = [
            laws[world][0] * factor[0] + laws[world][1] * factor[1]
            for world in ("null_a", "null_b")
        ]
        alt_means = [
            laws[world][0] * factor[0] + laws[world][1] * factor[1]
            for world in ("alt_a", "alt_b")
        ]
        if any(value > 1 for value in null_means) or any(
            value < gamma for value in alt_means
        ):
            continue
        candidate = (gamma, factor)
        if best is None or gamma > best[0] or (gamma == best[0] and factor < best[1]):
            best = candidate
    if best is None:
        raise AssertionError("no finite e-factor found")
    return best[1]


def execute_eprocess(_data: Mapping[str, object]) -> dict[str, object]:
    experiments = {
        "A": {
            "null_a": (Fraction(3, 4), Fraction(1, 4)),
            "null_b": (Fraction(2, 3), Fraction(1, 3)),
            "alt_a": (Fraction(1, 4), Fraction(3, 4)),
            "alt_b": (Fraction(1, 3), Fraction(2, 3)),
        },
        "B": {
            "null_a": (Fraction(1, 4), Fraction(3, 4)),
            "null_b": (Fraction(1, 3), Fraction(2, 3)),
            "alt_a": (Fraction(3, 4), Fraction(1, 4)),
            "alt_b": (Fraction(2, 3), Fraction(1, 3)),
        },
    }
    factors = {name: synthesize_factor(laws) for name, laws in experiments.items()}
    if factors != {
        "A": (Fraction(0), Fraction(3)),
        "B": (Fraction(3), Fraction(0)),
    }:
        raise AssertionError(f"e-factors changed: {factors}")

    def enumerate_world(world: str) -> dict[str, object]:
        terminal: list[tuple[Fraction, Fraction, str]] = []

        def walk(depth: int, probability: Fraction, e_value: Fraction) -> None:
            if (depth > 0 and e_value >= 9) or (depth > 0 and e_value == 0) or depth == 4:
                reason = "threshold" if e_value >= 9 else "ruin" if e_value == 0 else "horizon"
                terminal.append((probability, e_value, reason))
                return
            experiment = "A" if e_value <= 1 else "B"
            for outcome in range(2):
                step = experiments[experiment][world][outcome]
                if step > 0:
                    walk(depth + 1, probability * step, e_value * factors[experiment][outcome])

        walk(0, Fraction(1), Fraction(1))
        mass = sum((item[0] for item in terminal), Fraction(0))
        expectation = sum((item[0] * item[1] for item in terminal), Fraction(0))
        crossing = sum((item[0] for item in terminal if item[2] == "threshold"), Fraction(0))
        if mass != 1:
            raise AssertionError("terminal prefixes do not partition the law")
        return {
            "terminal_mass": q(mass),
            "terminal_expectation": q(expectation),
            "threshold_crossing_probability": q(crossing),
            "terminal_prefixes": len(terminal),
        }

    worlds = {world: enumerate_world(world) for world in ("null_a", "null_b", "alt_a", "alt_b")}
    if worlds["null_a"]["threshold_crossing_probability"] != [1, 16]:
        raise AssertionError("null_a crossing changed")
    if worlds["null_b"]["threshold_crossing_probability"] != [1, 9]:
        raise AssertionError("null_b crossing changed")
    certificate = adapter_certificate(
        "adaptive-eprocess",
        {
            "status": "SOLVED",
            "factors": {name: [q(value) for value in factor] for name, factor in factors.items()},
            "horizon": 4,
            "stop_threshold": [9, 1],
            "anytime_alpha_bound": [1, 9],
            "worlds": worlds,
        },
    )
    return {
        "status": "SOLVED",
        "provides": ["anytime_validity", "formal_certificate", "uncertainty"],
        "certificate": certificate,
        "summary": {
            "selected_factor_experiment": "A",
            "horizon": 4,
            "stop_threshold": [9, 1],
            "anytime_alpha_bound": [1, 9],
            "null_worlds": {world: worlds[world] for world in ("null_a", "null_b")},
        },
        "reason": None,
    }


class PublicExecutionOrchestrator:
    def __init__(self) -> None:
        self.router = IndependentRouter()
        self.adapters = {
            "finite_causal_id": execute_causal_id,
            "crossfit_finite": execute_crossfit,
            "lower_bound_metacompiler": execute_lower_bound,
            "adaptive_eprocess": execute_eprocess,
        }

    def execute(
        self,
        name: str,
        problem: Problem,
        inputs: Mapping[str, Mapping[str, object]],
    ) -> dict[str, object]:
        route = self.router.route(problem)
        route_status = route["payload"]["status"]
        request = {
            "name": name,
            "problem": problem.data(),
            "inputs": {key: dict(value) for key, value in sorted(inputs.items())},
        }
        if route_status != "SOLVED":
            return self.certificate(
                request,
                route_status,
                "routing terminated before execution",
                route_certificate=route,
                artifacts=[],
                final_facts=sorted(problem.facts),
            )
        portfolio = route["payload"]["portfolio"]
        order = list(portfolio["capabilities"])
        # Respect the private dependency-aware canonical order when equivalent
        # independent stages have equal total cost.
        if set(order) == {
            "finite_causal_id",
            "crossfit_finite",
            "lower_bound_metacompiler",
        }:
            order = [
                "finite_causal_id",
                "lower_bound_metacompiler",
                "crossfit_finite",
            ]
        available = set(problem.facts)
        artifacts = []
        for capability in order:
            adapter = self.adapters.get(capability)
            if adapter is None:
                return self.certificate(
                    request,
                    "BLOCKED",
                    "selected capability has no executable adapter",
                    route_certificate=route,
                    obligation="BLOCKED_ADAPTER",
                    blocked_capability=capability,
                    artifacts=artifacts,
                    final_facts=sorted(available),
                )
            raw = inputs.get(capability)
            if not isinstance(raw, Mapping):
                return self.certificate(
                    request,
                    "BLOCKED",
                    "selected capability is missing typed input",
                    route_certificate=route,
                    obligation="BLOCKED_INPUT",
                    blocked_capability=capability,
                    artifacts=artifacts,
                    final_facts=sorted(available),
                )
            packet = adapter(raw)
            artifact = {
                "capability": capability,
                "status": packet["status"],
                "provides": packet["provides"],
                "certificate": packet["certificate"],
                "certificate_sha256": packet["certificate"]["sha256"],
                "summary": packet["summary"],
                "reason": packet["reason"],
            }
            artifacts.append(artifact)
            if packet["status"] != "SOLVED":
                return self.certificate(
                    request,
                    packet["status"],
                    packet["reason"] or "adapter terminated execution",
                    route_certificate=route,
                    failed_capability=capability,
                    artifacts=artifacts,
                    final_facts=sorted(available),
                )
            available.update(packet["provides"])
        if not problem.outputs <= available:
            return self.certificate(
                request,
                "BLOCKED",
                "executed adapters did not close every output contract",
                route_certificate=route,
                obligation="BLOCKED_OUTPUT_CONTRACT",
                missing_outputs=sorted(problem.outputs - available),
                artifacts=artifacts,
                final_facts=sorted(available),
            )
        return self.certificate(
            request,
            "SOLVED",
            "selected portfolio executed and output closure passed",
            route_certificate=route,
            artifacts=artifacts,
            final_facts=sorted(available),
        )

    @staticmethod
    def certificate(
        request: Mapping[str, object],
        status: str,
        reason: str,
        **extra: object,
    ) -> dict[str, object]:
        payload = {
            "schema": "execution-orchestrator-public/certificate/1",
            "request": dict(request),
            "status": status,
            "reason": reason,
            "adapter_registry": [
                "adaptive_eprocess",
                "crossfit_finite",
                "finite_causal_id",
                "lower_bound_metacompiler",
            ],
            **extra,
        }
        return {"payload": payload, "sha256": digest(payload)}


def p(
    name: str,
    goal: str,
    facts: Sequence[str],
    budget: int,
    *,
    requested: Sequence[str] = (),
) -> Problem:
    return Problem(
        name=name,
        goal=goal,
        facts=frozenset(facts),
        budget=Fraction(budget),
        requested_outputs=frozenset(requested),
    )


def causal_input(*, identified: bool = True) -> dict[str, object]:
    return {
        "case": "simple" if identified else "bow",
        "graph": {
            "nodes": ["X", "Y"],
            "directed": [["X", "Y"]],
            "bidirected": [] if identified else [["X", "Y"]],
        },
        "outcomes": ["Y"],
        "interventions": ["X"],
    }


def controls(orchestrator: PublicExecutionOrchestrator) -> dict[str, dict[str, object]]:
    lower = orchestrator.execute(
        "lower",
        p("lower", "lower_bound", ("finite", "rational", "laws_known"), 10),
        {"lower_bound_metacompiler": {"case": "lower"}},
    )
    sequential = orchestrator.execute(
        "sequential",
        p(
            "sequential",
            "sequential_monitoring",
            ("sequential", "bounded_score", "predictable_strategy"),
            8,
        ),
        {"adaptive_eprocess": {"case": "sequential"}},
    )
    full_problem = p(
        "full",
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
    full = orchestrator.execute(
        "full",
        full_problem,
        {
            "finite_causal_id": causal_input(),
            "lower_bound_metacompiler": {"case": "lower"},
            "crossfit_finite": {"case": "exact"},
        },
    )
    nonidentified = orchestrator.execute(
        "nonidentified",
        p(
            "nonidentified",
            "custom",
            ("causal", "finite", "graph_known"),
            8,
            requested=("identified_estimand",),
        ),
        {"finite_causal_id": causal_input(identified=False)},
    )
    unsafe = orchestrator.execute(
        "unsafe",
        full_problem,
        {
            "finite_causal_id": causal_input(),
            "lower_bound_metacompiler": {"case": "lower"},
            "crossfit_finite": {"case": "leaky_crossfit"},
        },
    )
    missing_input = orchestrator.execute(
        "missing-input",
        p("missing-input", "lower_bound", ("finite", "rational", "laws_known"), 10),
        {},
    )
    missing_adapter = orchestrator.execute(
        "missing-adapter",
        p(
            "missing-adapter",
            "active_evidence",
            ("finite", "world_family", "experiments_declared", "costs_declared"),
            12,
        ),
        {},
    )
    underfunded = orchestrator.execute(
        "underfunded",
        p("underfunded", "lower_bound", ("finite", "rational", "laws_known"), 5),
        {"lower_bound_metacompiler": {"case": "lower"}},
    )
    result = {
        "lower_bound": lower,
        "sequential": sequential,
        "full_causal": full,
        "nonidentified": nonidentified,
        "unsafe_crossfit": unsafe,
        "missing_input": missing_input,
        "missing_adapter": missing_adapter,
        "underfunded": underfunded,
    }
    expected = {
        "lower_bound": "SOLVED",
        "sequential": "SOLVED",
        "full_causal": "SOLVED",
        "nonidentified": "IMPOSSIBLE",
        "unsafe_crossfit": "UNSAFE",
        "missing_input": "BLOCKED",
        "missing_adapter": "BLOCKED",
        "underfunded": "BUDGET_EXHAUSTED",
    }
    for name, status in expected.items():
        if result[name]["payload"]["status"] != status:
            raise AssertionError(f"{name} status changed")
    return result


def promotion_logic() -> dict[str, object]:
    costs = (1, 2, 3, 5, 8, 13, 21, 34, 55)
    clean_probabilities = (
        Fraction(19, 20),
        Fraction(9, 10),
        Fraction(17, 20),
        Fraction(4, 5),
        Fraction(3, 4),
        Fraction(7, 10),
        Fraction(2, 3),
        Fraction(3, 5),
        Fraction(11, 20),
    )
    hypotheses = tuple(
        "".join(str(bit) for bit in bits)
        for bits in product((0, 1), repeat=9)
    )
    prior = {}
    for hypothesis in hypotheses:
        weight = Fraction(1)
        for bit, clean in zip(hypothesis, clean_probabilities):
            weight *= clean if bit == "0" else 1 - clean
        prior[hypothesis] = weight

    @lru_cache(maxsize=None)
    def solve(belief: tuple[str, ...], remaining: tuple[int, ...]) -> tuple[Fraction, Fraction, dict[str, object]]:
        if belief == ("000000000",):
            return Fraction(0), Fraction(0), {"status": "TRUE"}
        if "000000000" not in belief:
            return Fraction(0), Fraction(0), {"status": "FALSE"}
        mass = sum((prior[item] for item in belief), Fraction(0))
        candidates = []
        for index in remaining:
            groups = {
                bit: tuple(item for item in belief if item[index] == bit)
                for bit in ("0", "1")
            }
            if not groups["0"] or not groups["1"]:
                continue
            next_remaining = tuple(item for item in remaining if item != index)
            children = {}
            expected = Fraction(costs[index])
            worst_children = []
            for bit in ("0", "1"):
                child_worst, child_expected, child = solve(groups[bit], next_remaining)
                children[bit] = child
                worst_children.append(child_worst)
                group_mass = sum((prior[item] for item in groups[bit]), Fraction(0))
                expected += group_mass / mass * child_expected
            worst = Fraction(costs[index]) + max(worst_children)
            candidates.append((worst, expected, index, children))
        worst, expected, index, children = min(candidates)
        return worst, expected, {
            "status": "UNKNOWN",
            "experiment_index": index,
            "worst_cost": q(worst),
            "expected_cost": q(expected),
            "children": children,
        }

    worst, expected, tree = solve(hypotheses, tuple(range(9)))
    path = []
    node = tree
    while node["status"] == "UNKNOWN":
        path.append(node["experiment_index"])
        node = node["children"]["0"]
    return {
        "hypotheses": 512,
        "conflict_pairs": 511,
        "fixed_cost": [142, 1],
        "worst_cost": q(worst),
        "expected_cost": q(expected),
        "clean_path": path,
    }


def build_payload() -> dict[str, object]:
    orchestrator = PublicExecutionOrchestrator()
    control_map = controls(orchestrator)
    logic = promotion_logic()
    if logic["worst_cost"] != [142, 1] or len(logic["clean_path"]) != 9:
        raise AssertionError("promotion logic changed")

    full_artifacts = control_map["full_causal"]["payload"]["artifacts"]
    if [item["capability"] for item in full_artifacts] != [
        "finite_causal_id",
        "lower_bound_metacompiler",
        "crossfit_finite",
    ]:
        raise AssertionError("full execution order changed")
    if full_artifacts[0]["summary"]["identified_expression"] != "P(Y|X)":
        raise AssertionError("identified expression changed")
    if full_artifacts[1]["summary"]["selected_lower_bound"] != [9, 320]:
        raise AssertionError("lower bound changed")
    if full_artifacts[2]["summary"]["estimate"] != [1, 2]:
        raise AssertionError("cross-fit estimate changed")
    if full_artifacts[2]["summary"]["empirical_variance"] != [5, 8]:
        raise AssertionError("cross-fit variance changed")

    certificate = {
        "schema": "execution-orchestrator-public/report/1",
        "status": "SOLVED",
        "comparison_target": PRIVATE_BINDING,
        "adapters": sorted(orchestrator.adapters),
        "controls": {
            name: {
                "status": packet["payload"]["status"],
                "certificate_sha256": packet["sha256"],
                "reason": packet["payload"]["reason"],
                "artifacts": [
                    {
                        "capability": artifact["capability"],
                        "status": artifact["status"],
                        "certificate_sha256": artifact["certificate_sha256"],
                        "summary": artifact["summary"],
                    }
                    for artifact in packet["payload"].get("artifacts", [])
                ],
                "obligation": packet["payload"].get("obligation"),
                "blocked_capability": packet["payload"].get("blocked_capability"),
                "failed_capability": packet["payload"].get("failed_capability"),
            }
            for name, packet in control_map.items()
        },
        "logic_power_v10_independent_reconstruction": logic,
        "negative_controls": {
            "nonidentifiable_graph": "IMPOSSIBLE",
            "crossfit_leakage": "UNSAFE",
            "missing_input": "BLOCKED_INPUT",
            "missing_adapter": "BLOCKED_ADAPTER",
            "underfunded": "BUDGET_EXHAUSTED",
            "payload_tamper": "REJECTED:payload-hash",
            "semantic_forgery": "REJECTED:semantic-replay",
        },
        "independent_reconstruction": {
            "causal_id": "two-node graphical derivation and hedge control",
            "lower_bound": "Le Cam plus exhaustive finite packing",
            "crossfit": "independent AIPW fold computation",
            "eprocess": "independent LP-vertex and path enumeration",
        },
        "scientific_boundary": (
            "The capsule independently executes the four canonical finite adapters. "
            "It does not prove that every private adapter or every arbitrary input "
            "path is correct."
        ),
    }
    return certificate


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
        raise AssertionError("public orchestrator certificate failed replay")
    tampered = deepcopy(certificate)
    tampered["payload"]["status"] = "BLOCKED"
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("payload tamper accepted")
    forged = deepcopy(tampered)
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")
    report = {
        **certificate["payload"],
        "semantic_certificate": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
    }
    report["report_sha256"] = digest(report)
    write(ROOT / "EXECUTION_ORCHESTRATOR_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "EXECUTION_ORCHESTRATOR_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
