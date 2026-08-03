from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import random
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent
MONTE_CARLO_TRIALS = 4096
CHAOS_SEEDS = 256
CONTROL_COUNT = 5
REQUIRED_STRESS_CASES = MONTE_CARLO_TRIALS + CONTROL_COUNT * CHAOS_SEEDS
PRIVATE_TARGET = {
    "repository": "cristh99/my_first_repository",
    "pull_request": 86,
    "head": "e64c82f8ab1fe8f15996ce2159267465d91f36e9",
}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def frac(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("fraction must be [numerator, denominator]")
    numerator, denominator = value
    if not isinstance(numerator, int) or not isinstance(denominator, int) or denominator <= 0:
        raise ValueError("invalid rational")
    return Fraction(numerator, denominator)


@dataclass(frozen=True)
class Problem:
    name: str
    theta: Fraction
    estimates: tuple[Fraction, ...]
    biases: tuple[Fraction, ...]
    radii: tuple[Fraction, ...]
    costs: tuple[Fraction, ...]

    def __post_init__(self) -> None:
        lengths = {len(self.estimates), len(self.biases), len(self.radii), len(self.costs)}
        if len(lengths) != 1 or not self.estimates:
            raise ValueError("multiscale vectors must have one nonzero length")

    @property
    def levels(self) -> int:
        return len(self.estimates)

    def data(self) -> dict[str, object]:
        return {
            "name": self.name,
            "theta": q(self.theta),
            "levels": [
                {
                    "level": index,
                    "estimate": q(self.estimates[index]),
                    "bias": q(self.biases[index]),
                    "radius": q(self.radii[index]),
                    "cost": q(self.costs[index]),
                }
                for index in range(self.levels)
            ],
        }


def status(problem: Problem) -> str:
    if problem.levels < 2:
        return "UNKNOWN_MULTISCALE_DEPTH"
    if any(value < 0 for value in problem.biases):
        return "INVALID_BIAS_BOUND"
    if any(value <= 0 for value in problem.radii):
        return "INVALID_CONFIDENCE_RADIUS"
    if any(value < 0 for value in problem.costs):
        return "INVALID_EXPERIMENT_COST"
    if any(problem.biases[index + 1] > problem.biases[index] for index in range(problem.levels - 1)):
        return "INVALID_BIAS_MONOTONICITY"
    if any(problem.radii[index + 1] < problem.radii[index] for index in range(problem.levels - 1)):
        return "INVALID_RADIUS_MONOTONICITY"
    if any(problem.radii[index + 1] > 2 * problem.radii[index] for index in range(problem.levels - 1)):
        return "INVALID_RADIUS_GROWTH"
    if any(
        abs(problem.estimates[index] - problem.theta) > problem.biases[index] + problem.radii[index]
        for index in range(problem.levels)
    ):
        return "INVALID_SIMULTANEOUS_EVENT"
    return "PASS"


def stable_pair(problem: Problem, coarse: int, fine: int) -> bool:
    return abs(problem.estimates[coarse] - problem.estimates[fine]) <= 2 * (
        problem.radii[coarse] + problem.radii[fine]
    )


def stable(problem: Problem, level: int) -> bool:
    return all(stable_pair(problem, level, fine) for fine in range(level + 1, problem.levels))


def selected_level(problem: Problem) -> int:
    return next(level for level in range(problem.levels) if stable(problem, level))


def balanced_level(problem: Problem) -> int | None:
    return next(
        (index for index, (bias, radius) in enumerate(zip(problem.biases, problem.radii)) if bias <= radius),
        None,
    )


def instability_chain(problem: Problem, oracle: int, selected: int) -> list[dict[str, object]]:
    chain: list[dict[str, object]] = []
    current = oracle
    while current < selected:
        if stable(problem, current):
            raise AssertionError("level before selected is unexpectedly stable")
        witness = next(
            fine for fine in range(current + 1, problem.levels) if not stable_pair(problem, current, fine)
        )
        if not problem.radii[witness] < 2 * problem.biases[current]:
            raise AssertionError("instability radius implication failed")
        chain.append(
            {
                "coarse": current,
                "witness": witness,
                "witness_radius": q(problem.radii[witness]),
                "upper_bound": q(2 * problem.biases[current]),
            }
        )
        current = witness
    return chain


def compile_problem(problem: Problem, *, committed_before_estimates: bool = True) -> dict[str, object]:
    if not committed_before_estimates:
        return {"status": "INVALID_POST_HOC_SELECTION", "problem": problem.data()}
    structural = status(problem)
    if structural != "PASS":
        return {"status": structural, "problem": problem.data()}
    balance = balanced_level(problem)
    if balance is None:
        return {"status": "UNKNOWN_BALANCE_POINT", "problem": problem.data()}

    selected = selected_level(problem)
    risks = tuple(bias + radius for bias, radius in zip(problem.biases, problem.radii))
    oracle_risk = min(risks)
    oracle = min(range(problem.levels), key=lambda index: (risks[index], index))
    error = abs(problem.estimates[selected] - problem.theta)

    if selected < oracle:
        proof_case = "SELECTED_COARSER_THAN_ORACLE"
        if not stable_pair(problem, selected, oracle):
            raise AssertionError("selected level is not stable to oracle")
        derived = 2 * (problem.radii[selected] + problem.radii[oracle]) + oracle_risk
        if derived > 5 * oracle_risk:
            raise AssertionError("coarser-case factor-five proof failed")
        chain: list[dict[str, object]] = []
    elif selected == oracle:
        proof_case = "SELECTED_EQUALS_ORACLE"
        derived = oracle_risk
        chain = []
    else:
        proof_case = "SELECTED_FINER_THAN_ORACLE"
        chain = instability_chain(problem, oracle, selected)
        if not chain or int(chain[-1]["witness"]) < selected:
            raise AssertionError("instability chain did not reach selected level")
        if not problem.radii[selected] < 2 * problem.biases[oracle]:
            raise AssertionError("selected radius is not bounded by oracle bias")
        derived = 3 * problem.biases[oracle]
        if derived > 3 * oracle_risk:
            raise AssertionError("finer-case factor-three proof failed")

    if error > derived or error > 5 * oracle_risk:
        return {"status": "INVALID_SHARP_ORACLE_CERTIFICATE", "problem": problem.data()}

    return {
        "status": "SOLVED",
        "problem": problem.data(),
        "selected_level": selected,
        "balanced_level": balance,
        "oracle_level": oracle,
        "selected_error": q(error),
        "oracle_risk": q(oracle_risk),
        "realized_oracle_ratio": q(error / oracle_risk),
        "sharp_factor": [5, 1],
        "sharp_bound": q(5 * oracle_risk),
        "proof_case": proof_case,
        "derived_case_bound": q(derived),
        "instability_chain": chain,
    }


def controls() -> tuple[Problem, ...]:
    radii = (
        Fraction(1, 128), Fraction(1, 64), Fraction(1, 32),
        Fraction(1, 16), Fraction(1, 8), Fraction(1, 4),
    )
    costs = tuple(Fraction(2**index) for index in range(6))
    families = (
        (Fraction(3, 128), Fraction(1, 128), Fraction(1, 256), Fraction(1, 512), Fraction(1, 1024), Fraction(1, 2048)),
        (Fraction(1, 4), Fraction(3, 64), Fraction(1, 64), Fraction(1, 128), Fraction(1, 256), Fraction(1, 512)),
        (Fraction(1, 2), Fraction(1, 4), Fraction(3, 32), Fraction(1, 32), Fraction(1, 64), Fraction(1, 128)),
        (Fraction(1), Fraction(1, 2), Fraction(1, 4), Fraction(3, 16), Fraction(1, 16), Fraction(1, 32)),
        (Fraction(2), Fraction(1), Fraction(1, 2), Fraction(1, 2), Fraction(3, 8), Fraction(1, 8)),
    )
    result: list[Problem] = []
    for index, biases in enumerate(families, start=1):
        provisional = Problem(
            name=f"regularity-{index}", theta=Fraction(0),
            estimates=tuple(Fraction(0) for _ in radii), biases=biases,
            radii=radii, costs=costs,
        )
        balance = balanced_level(provisional)
        if balance is None:
            raise AssertionError("control lacks balance point")
        estimates = tuple(
            (biases[level] + radii[level]) * (1 if level == balance else -1)
            for level in range(6)
        )
        result.append(replace(provisional, estimates=estimates))
    return tuple(result)


def tightness() -> Problem:
    return Problem(
        name="factor-five-tightness", theta=Fraction(0),
        estimates=(Fraction(5), Fraction(1)), biases=(Fraction(4), Fraction(0)),
        radii=(Fraction(1), Fraction(1)), costs=(Fraction(1), Fraction(2)),
    )


def prefix_obstructions(problem: Problem) -> list[dict[str, object]]:
    return [
        {
            "level": level,
            "common_prefix": [[0, 1] for _ in range(level + 1)],
            "safe_decision": "STOP",
            "unsafe_decision": "CONTINUE",
            "separating_level": level + 1,
            "separating_cost": q(problem.costs[level + 1]),
            "status": "IMPOSSIBLE_BEFORE_NEXT_LEVEL",
        }
        for level in range(problem.levels - 1)
    ]


def random_problem(rng: random.Random, trial: int) -> Problem:
    levels = rng.randint(3, 8)
    factors = (Fraction(1), Fraction(5, 4), Fraction(3, 2), Fraction(7, 4), Fraction(2))
    radii = [Fraction(rng.randint(1, 4), 2048)]
    for _ in range(1, levels):
        radii.append(radii[-1] * rng.choice(factors))
    balance = rng.randrange(levels)
    biases = [Fraction(0) for _ in range(levels)]
    biases[balance] = radii[balance] * rng.choice((Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1)))
    for index in range(balance - 1, -1, -1):
        biases[index] = max(
            biases[index + 1],
            radii[index] * rng.choice((Fraction(5, 4), Fraction(3, 2), Fraction(2), Fraction(3))),
        )
    for index in range(balance + 1, levels):
        biases[index] = biases[index - 1] * rng.choice((Fraction(1), Fraction(3, 4), Fraction(1, 2), Fraction(1, 4)))
    theta = Fraction(rng.randint(-32, 32), 32)
    estimates = tuple(
        theta + Fraction(rng.randint(-16, 16), 16) * (biases[index] + radii[index])
        for index in range(levels)
    )
    return Problem(
        name=f"mc-{trial}", theta=theta, estimates=estimates,
        biases=tuple(biases), radii=tuple(radii),
        costs=tuple(Fraction(2**index) for index in range(levels)),
    )


def monte_carlo(trials: int = MONTE_CARLO_TRIALS, seed: int = 20260803) -> dict[str, object]:
    rng = random.Random(seed)
    maximum = Fraction(0)
    cases_by_proof = {
        "SELECTED_COARSER_THAN_ORACLE": 0,
        "SELECTED_EQUALS_ORACLE": 0,
        "SELECTED_FINER_THAN_ORACLE": 0,
    }
    for trial in range(trials):
        packet = compile_problem(random_problem(rng, trial))
        if packet["status"] != "SOLVED":
            raise AssertionError(f"Monte Carlo case failed: {packet['status']}")
        ratio = frac(packet["realized_oracle_ratio"])
        maximum = max(maximum, ratio)
        cases_by_proof[str(packet["proof_case"])] += 1
        if ratio > 5:
            raise AssertionError("Monte Carlo falsified factor five")
    return {
        "method": "seeded_exact_rational_monte_carlo",
        "seed": seed,
        "trials": trials,
        "max_oracle_ratio": q(maximum),
        "proof_case_counts": cases_by_proof,
        "violations": 0,
        "epistemic_status": "FALSIFIER_NOT_PROOF",
    }


def tent(value: Fraction) -> Fraction:
    return 2 * value if value <= Fraction(1, 2) else 2 * (1 - value)


def chaos_stress(seeds: int = CHAOS_SEEDS) -> dict[str, object]:
    maximum = Fraction(0)
    max_jump = 0
    perturbation = Fraction(1, 65_536)
    cases = 0
    for base in controls():
        for seed in range(1, seeds + 1):
            state = Fraction(seed, seeds + 1)
            estimates: list[Fraction] = []
            for level in range(base.levels):
                state = tent(state)
                estimates.append(
                    base.theta + (2 * state - 1) * (base.biases[level] + base.radii[level])
                )
            problem = replace(base, name=f"tent-{base.name}-{seed}", estimates=tuple(estimates))
            packet = compile_problem(problem)
            if packet["status"] != "SOLVED":
                raise AssertionError("tent-map case failed")
            ratio = frac(packet["realized_oracle_ratio"])
            maximum = max(maximum, ratio)
            selected = int(packet["selected_level"])
            for level in range(problem.levels):
                for direction in (-1, 1):
                    perturbed = list(problem.estimates)
                    candidate = perturbed[level] + direction * perturbation
                    if abs(candidate - problem.theta) > problem.biases[level] + problem.radii[level]:
                        continue
                    perturbed[level] = candidate
                    changed = compile_problem(replace(problem, estimates=tuple(perturbed)))
                    if changed["status"] != "SOLVED":
                        raise AssertionError("admissible tent perturbation failed")
                    max_jump = max(max_jump, abs(int(changed["selected_level"]) - selected))
            if ratio > 5:
                raise AssertionError("tent-map stress falsified factor five")
            cases += 1
    return {
        "method": "exact_rational_tent_map_sensitivity",
        "seeds_per_control": seeds,
        "cases": cases,
        "perturbation": q(perturbation),
        "max_selector_jump": max_jump,
        "max_oracle_ratio": q(maximum),
        "violations": 0,
        "epistemic_status": "CHAOS_INSPIRED_FALSIFIER_NOT_PROOF",
    }


GATES = (
    ("typed_problem", Fraction(1), Fraction(19, 20)),
    ("bias_monotonicity", Fraction(2), Fraction(9, 10)),
    ("radius_monotonicity", Fraction(4), Fraction(17, 20)),
    ("radius_doubling", Fraction(8), Fraction(4, 5)),
    ("simultaneous_event", Fraction(16), Fraction(3, 4)),
    ("predictable_selector", Fraction(32), Fraction(7, 10)),
    ("sharp_oracle_proof", Fraction(5), Fraction(2, 3)),
    ("independent_falsification", Fraction(7), Fraction(3, 5)),
)
ASSIGNMENTS = tuple(product((0, 1), repeat=len(GATES)))
PRIOR = {
    assignment: _prior_weight
    for assignment in ASSIGNMENTS
    for _prior_weight in [
        Fraction(1)
    ]
}
for assignment in ASSIGNMENTS:
    weight = Fraction(1)
    for bit, (_name, _cost, clean_probability) in zip(assignment, GATES):
        weight *= clean_probability if bit == 0 else 1 - clean_probability
    PRIOR[assignment] = weight


def mass(state: tuple[tuple[int, ...], ...]) -> Fraction:
    return sum((PRIOR[item] for item in state), Fraction(0))


def verdict(assignment: tuple[int, ...]) -> bool:
    return all(bit == 0 for bit in assignment)


@lru_cache(maxsize=None)
def solve_policy(
    state: tuple[tuple[int, ...], ...],
    available: tuple[int, ...],
) -> tuple[Fraction, Fraction, dict[str, object]]:
    verdicts = {verdict(item) for item in state}
    if len(verdicts) == 1:
        return Fraction(0), Fraction(0), {
            "status": "TRUE" if True in verdicts else "FALSE",
            "hypotheses": len(state),
        }
    current_mass = mass(state)
    candidates = []
    for gate in available:
        groups = {
            observation: tuple(item for item in state if item[gate] == observation)
            for observation in (0, 1)
        }
        remaining = tuple(index for index in available if index != gate)
        children = {
            observation: solve_policy(group, remaining)
            for observation, group in groups.items()
            if group
        }
        expected = GATES[gate][1] + sum(
            (mass(groups[observation]) / current_mass) * child[0]
            for observation, child in children.items()
        )
        worst = GATES[gate][1] + max(child[1] for child in children.values())
        tree = {
            "status": "UNKNOWN",
            "experiment": GATES[gate][0],
            "children": {str(observation): child[2] for observation, child in children.items()},
        }
        candidates.append((expected, worst, GATES[gate][0], tree))
    expected, worst, _name, tree = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    return expected, worst, tree


def clean_path(tree: Mapping[str, object]) -> list[str]:
    path: list[str] = []
    node = tree
    while node.get("status") == "UNKNOWN":
        path.append(str(node["experiment"]))
        node = node["children"]["0"]
    if node.get("status") != "TRUE":
        raise AssertionError("clean gate path must terminate TRUE")
    return path


def logic_power_analysis() -> dict[str, object]:
    initial = tuple(ASSIGNMENTS)
    expected, worst, tree = solve_policy(initial, tuple(range(len(GATES))))
    path = clean_path(tree)
    if set(path) != {item[0] for item in GATES}:
        raise AssertionError("optimal gate policy omitted a gate")
    return {
        "hypotheses": len(ASSIGNMENTS),
        "conflict_pairs": 255,
        "fixed_basis": [item[0] for item in GATES],
        "fixed_basis_cost": q(sum((item[1] for item in GATES), Fraction(0))),
        "adaptive_expected_cost": q(expected),
        "adaptive_worst_cost": q(worst),
        "clean_path": path,
        "policy_tree": tree,
    }


def negative_controls() -> dict[str, str]:
    base = controls()[2]
    bad_bias = list(base.biases)
    bad_bias[2] = bad_bias[1] + Fraction(1, 128)
    bad_radius = list(base.radii)
    bad_radius[2] = bad_radius[1] - Fraction(1, 256)
    bad_growth = list(base.radii)
    bad_growth[1] = 3 * bad_growth[0]
    for index in range(2, len(bad_growth)):
        bad_growth[index] = max(bad_growth[index], bad_growth[index - 1])
    bad_event = list(base.estimates)
    bad_event[0] = base.theta + base.biases[0] + base.radii[0] + Fraction(1, 4096)
    no_balance = replace(
        base,
        biases=tuple(2 * base.radii[-1] for _ in base.radii),
        estimates=tuple(base.theta for _ in base.radii),
    )
    return {
        "bias_monotonicity": compile_problem(replace(base, biases=tuple(bad_bias)))["status"],
        "radius_monotonicity": compile_problem(replace(base, radii=tuple(bad_radius)))["status"],
        "radius_growth": compile_problem(replace(base, radii=tuple(bad_growth)))["status"],
        "simultaneous_event": compile_problem(replace(base, estimates=tuple(bad_event)))["status"],
        "no_balance": compile_problem(no_balance)["status"],
        "post_hoc_selection": compile_problem(base, committed_before_estimates=False)["status"],
        "resource": "UNKNOWN_RESOURCE_LIMIT",
    }


def build_payload(max_stress_cases: int = REQUIRED_STRESS_CASES) -> dict[str, object]:
    if max_stress_cases < REQUIRED_STRESS_CASES:
        return {
            "status": "UNKNOWN_RESOURCE_LIMIT",
            "required_stress_cases": REQUIRED_STRESS_CASES,
            "declared_limit": max_stress_cases,
        }
    control_packets = [compile_problem(problem) for problem in controls()]
    if [packet["selected_level"] for packet in control_packets] != [1, 2, 3, 4, 5]:
        raise AssertionError("control selection changed")
    if any(packet["realized_oracle_ratio"] != [1, 1] for packet in control_packets):
        raise AssertionError("control oracle matching changed")
    tight = compile_problem(tightness())
    if tight["realized_oracle_ratio"] != [5, 1]:
        raise AssertionError("factor-five tightness changed")
    negatives = negative_controls()
    expected_negatives = {
        "bias_monotonicity": "INVALID_BIAS_MONOTONICITY",
        "radius_monotonicity": "INVALID_RADIUS_MONOTONICITY",
        "radius_growth": "INVALID_RADIUS_GROWTH",
        "simultaneous_event": "INVALID_SIMULTANEOUS_EVENT",
        "no_balance": "UNKNOWN_BALANCE_POINT",
        "post_hoc_selection": "INVALID_POST_HOC_SELECTION",
        "resource": "UNKNOWN_RESOURCE_LIMIT",
    }
    if negatives != expected_negatives:
        raise AssertionError(f"negative controls changed: {negatives}")
    return {
        "status": "SOLVED",
        "schema": "sharp-multiscale-adaptation-independent-public/1",
        "comparison_target": PRIVATE_TARGET,
        "theorem": {
            "statement": "selected_error <= 5 * min_k(b_k+r_k)",
            "sharpness": "a two-level rational witness attains exactly five",
        },
        "controls": control_packets,
        "tightness_witness": tight,
        "prefix_obstructions": prefix_obstructions(controls()[-1]),
        "monte_carlo": monte_carlo(),
        "chaos_stress": chaos_stress(),
        "logic_power_v10": logic_power_analysis(),
        "negative_controls": negatives,
        "resources": {
            "monte_carlo_trials": MONTE_CARLO_TRIALS,
            "chaos_cases": CONTROL_COUNT * CHAOS_SEEDS,
            "total_stress_cases": REQUIRED_STRESS_CASES,
        },
        "scientific_boundary": (
            "Exact deterministic theorem for finite rational multiscale sequences. "
            "Monte Carlo and tent-map campaigns are falsifiers, not proof. The "
            "result does not establish continuous minimax adaptation or arbitrary dependence."
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
    expected = build_certificate()
    if canonical_json(expected["payload"]) != canonical_json(payload):
        return ["semantic-replay"]
    return []


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("certificate failed self replay")
    tampered = deepcopy(certificate)
    tampered["payload"]["tightness_witness"]["realized_oracle_ratio"] = [4, 1]
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["tightness_witness"]["realized_oracle_ratio"] = [4, 1]
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")
    low_resource = build_payload(REQUIRED_STRESS_CASES - 1)
    if low_resource["status"] != "UNKNOWN_RESOURCE_LIMIT":
        raise AssertionError("resource control did not fail closed")
    report = {
        **certificate["payload"],
        "resource_negative": low_resource,
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
    }
    report["sha256"] = digest(report)
    (ROOT / "SHARP_MULTISCALE_ADAPTATION_PUBLIC_CERTIFICATE.json").write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n"
    )
    (ROOT / "SHARP_MULTISCALE_ADAPTATION_PUBLIC_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
