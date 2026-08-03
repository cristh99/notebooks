from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
from typing import Sequence

from logic_power_v10 import (
    ActiveDiscoveryProblem,
    Experiment,
    build_certificate,
    verify_certificate,
)
from logic_power_v10.certificate import canonical_json


ROOT = Path(__file__).resolve().parent


def fdata(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def solve_square(
    matrix: Sequence[Sequence[Fraction]],
    rhs: Sequence[Fraction],
) -> list[Fraction] | None:
    n = len(matrix)
    augmented = [
        [Fraction(x) for x in matrix[row]] + [Fraction(rhs[row])]
        for row in range(n)
    ]
    for column in range(n):
        pivot = next(
            (row for row in range(column, n) if augmented[row][column]),
            None,
        )
        if pivot is None:
            return None
        augmented[column], augmented[pivot] = (
            augmented[pivot],
            augmented[column],
        )
        divisor = augmented[column][column]
        augmented[column] = [x / divisor for x in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            multiplier = augmented[row][column]
            if multiplier:
                augmented[row] = [
                    augmented[row][index]
                    - multiplier * augmented[column][index]
                    for index in range(n + 1)
                ]
    return [augmented[row][-1] for row in range(n)]


def solve_factor(
    null_laws: Sequence[tuple[Fraction, Fraction]],
    alternative_laws: Sequence[tuple[Fraction, Fraction]],
) -> dict[str, object]:
    """Independent exact LP replay for a two-outcome composite e-factor."""

    # Variables are factor[0], factor[1], gamma.
    rows: list[tuple[tuple[Fraction, ...], Fraction]] = [
        ((1, 0, 0), Fraction(0)),
        ((0, 1, 0), Fraction(0)),
    ]
    rows.extend((law + (Fraction(0),), Fraction(1)) for law in null_laws)
    rows.extend(
        (law + (Fraction(-1),), Fraction(0))
        for law in alternative_laws
    )
    best: tuple[Fraction, tuple[Fraction, Fraction]] | None = None
    examined = 0
    feasible = 0
    for active in combinations(range(len(rows)), 3):
        examined += 1
        solution = solve_square(
            [rows[index][0] for index in active],
            [rows[index][1] for index in active],
        )
        if solution is None:
            continue
        factor = (solution[0], solution[1])
        gamma = solution[2]
        if min(factor) < 0:
            continue
        null_expectations = tuple(
            sum((law[index] * factor[index] for index in range(2)), Fraction())
            for law in null_laws
        )
        alternative_expectations = tuple(
            sum((law[index] * factor[index] for index in range(2)), Fraction())
            for law in alternative_laws
        )
        if max(null_expectations) > 1:
            continue
        if min(alternative_expectations) < gamma:
            continue
        feasible += 1
        candidate = (gamma, factor)
        if best is None or gamma > best[0] or (
            gamma == best[0] and factor < best[1]
        ):
            best = candidate
    if best is None:
        raise AssertionError("no factor vertex found")
    gamma, factor = best
    return {
        "gamma": fdata(gamma),
        "factor": {"0": fdata(factor[0]), "1": fdata(factor[1])},
        "null_expectations": [
            fdata(
                sum(
                    (law[index] * factor[index] for index in range(2)),
                    Fraction(),
                )
            )
            for law in null_laws
        ],
        "alternative_expectations": [
            fdata(
                sum(
                    (law[index] * factor[index] for index in range(2)),
                    Fraction(),
                )
            )
            for law in alternative_laws
        ],
        "vertices_examined": examined,
        "feasible_vertices": feasible,
    }


def enumerate_world(
    law_a: tuple[Fraction, Fraction],
    law_b: tuple[Fraction, Fraction],
    *,
    horizon: int = 4,
    threshold: Fraction = Fraction(9),
) -> dict[str, object]:
    factors = {
        "A": (Fraction(0), Fraction(3)),
        "B": (Fraction(3), Fraction(0)),
    }
    laws = {"A": law_a, "B": law_b}
    paths: list[tuple[Fraction, Fraction, str]] = []

    def walk(depth: int, probability: Fraction, e_value: Fraction) -> None:
        if depth and e_value >= threshold:
            paths.append((probability, e_value, "threshold"))
            return
        if depth and e_value == 0:
            paths.append((probability, e_value, "ruin"))
            return
        if depth == horizon:
            paths.append((probability, e_value, "horizon"))
            return
        experiment = "A" if e_value <= 1 else "B"
        for outcome in range(2):
            step = laws[experiment][outcome]
            if step:
                walk(
                    depth + 1,
                    probability * step,
                    e_value * factors[experiment][outcome],
                )

    walk(0, Fraction(1), Fraction(1))
    mass = sum((probability for probability, _, _ in paths), Fraction())
    expectation = sum(
        (probability * value for probability, value, _ in paths),
        Fraction(),
    )
    crossing = sum(
        (
            probability
            for probability, _, reason in paths
            if reason == "threshold"
        ),
        Fraction(),
    )
    if mass != 1:
        raise AssertionError("terminal paths do not partition the law")
    return {
        "terminal_mass": fdata(mass),
        "terminal_expectation": fdata(expectation),
        "crossing_probability": fdata(crossing),
        "terminal_prefixes": len(paths),
    }


def post_selection_counterexample() -> dict[str, object]:
    null = (Fraction(1, 2), Fraction(1, 2))
    factor = (Fraction(1, 2), Fraction(3, 2))
    single = sum((null[i] * factor[i] for i in range(2)), Fraction())
    predictable_average = sum(
        (
            null[left]
            * null[right]
            * (factor[left] + factor[right])
            / 2
            for left, right in product(range(2), repeat=2)
        ),
        Fraction(),
    )
    posthoc_maximum = sum(
        (
            null[left]
            * null[right]
            * max(factor[left], factor[right])
            for left, right in product(range(2), repeat=2)
        ),
        Fraction(),
    )
    if (single, predictable_average, posthoc_maximum) != (
        Fraction(1),
        Fraction(1),
        Fraction(5, 4),
    ):
        raise AssertionError("post-selection control changed")
    return {
        "single": fdata(single),
        "predictable_average": fdata(predictable_average),
        "posthoc_maximum": fdata(posthoc_maximum),
        "inflation": fdata(posthoc_maximum - 1),
    }


def gate_problem() -> ActiveDiscoveryProblem:
    gates = (
        ("null_factor", Fraction(2), Fraction(1, 4)),
        ("alt_growth", Fraction(2), Fraction(1, 6)),
        ("predictability", Fraction(1), Fraction(1, 3)),
        ("prefix_partition", Fraction(1), Fraction(1, 5)),
        ("optional_stopping", Fraction(2), Fraction(1, 5)),
        ("independent_replay", Fraction(3), Fraction(1, 10)),
        ("tamper_rejection", Fraction(1), Fraction(1, 8)),
    )
    hypotheses = tuple(
        format(value, f"0{len(gates)}b")
        for value in range(2 ** len(gates))
    )
    experiments = tuple(
        Experiment(
            name=name,
            cost=cost,
            observations={
                hypothesis: hypothesis[index] for hypothesis in hypotheses
            },
        )
        for index, (name, cost, _) in enumerate(gates)
    )
    prior: dict[str, Fraction] = {}
    for hypothesis in hypotheses:
        weight = Fraction(1)
        for index, (_, _, defect) in enumerate(gates):
            weight *= defect if hypothesis[index] == "1" else 1 - defect
        prior[hypothesis] = weight
    return ActiveDiscoveryProblem(
        hypotheses=hypotheses,
        property_values={
            hypothesis: "1" not in hypothesis for hypothesis in hypotheses
        },
        experiments=experiments,
        prior=prior,
    )


def clean_path(tree: dict[str, object]) -> list[str]:
    order: list[str] = []
    node = tree
    while node.get("status") == "UNKNOWN":
        experiment = node["experiment"]
        order.append(str(experiment))
        children = node["children"]
        if not isinstance(children, dict):
            raise AssertionError("malformed policy")
        next_node = children["0"]
        if not isinstance(next_node, dict):
            raise AssertionError("malformed clean branch")
        node = next_node
    if node.get("status") != "TRUE":
        raise AssertionError("clean branch did not terminate TRUE")
    return order


def main() -> None:
    null_a_a = (Fraction(3, 4), Fraction(1, 4))
    null_b_a = (Fraction(2, 3), Fraction(1, 3))
    alt_a_a = (Fraction(1, 4), Fraction(3, 4))
    alt_b_a = (Fraction(1, 3), Fraction(2, 3))
    factor_a = solve_factor(
        (null_a_a, null_b_a), (alt_a_a, alt_b_a)
    )

    null_a_b = (Fraction(1, 4), Fraction(3, 4))
    null_b_b = (Fraction(1, 3), Fraction(2, 3))
    alt_a_b = (Fraction(3, 4), Fraction(1, 4))
    alt_b_b = (Fraction(2, 3), Fraction(1, 3))
    factor_b = solve_factor(
        (null_a_b, null_b_b), (alt_a_b, alt_b_b)
    )

    if factor_a["factor"] != {"0": [0, 1], "1": [3, 1]}:
        raise AssertionError("factor A mismatch")
    if factor_b["factor"] != {"0": [3, 1], "1": [0, 1]}:
        raise AssertionError("factor B mismatch")
    if factor_a["gamma"] != [2, 1] or factor_b["gamma"] != [2, 1]:
        raise AssertionError("factor growth mismatch")

    sequential = {
        "null_a": enumerate_world(null_a_a, null_a_b),
        "null_b": enumerate_world(null_b_a, null_b_b),
        "alt_a": enumerate_world(alt_a_a, alt_a_b),
        "alt_b": enumerate_world(alt_b_a, alt_b_b),
    }
    expected_sequential = {
        "null_a": ([9, 16], [1, 16]),
        "null_b": ([1, 1], [1, 9]),
        "alt_a": ([81, 16], [9, 16]),
        "alt_b": ([4, 1], [4, 9]),
    }
    for world, (expectation, crossing) in expected_sequential.items():
        if sequential[world]["terminal_expectation"] != expectation:
            raise AssertionError(f"{world} expectation mismatch")
        if sequential[world]["crossing_probability"] != crossing:
            raise AssertionError(f"{world} crossing mismatch")
        if sequential[world]["terminal_prefixes"] != 3:
            raise AssertionError(f"{world} terminal-prefix count mismatch")

    gate_certificate = build_certificate(
        gate_problem(), "adaptive_eprocess_public_replay"
    )
    gate_errors = verify_certificate(gate_certificate)
    if gate_errors:
        raise AssertionError(f"gate certificate replay failed: {gate_errors}")
    analysis = gate_certificate["payload"]["analysis"]
    order = clean_path(analysis["policy"]["tree"])
    expected_order = [
        "predictability",
        "prefix_partition",
        "null_factor",
        "tamper_rejection",
        "optional_stopping",
        "alt_growth",
        "independent_replay",
    ]
    if order != expected_order:
        raise AssertionError(f"unexpected gate order: {order}")
    if analysis["fixed_basis_cost"] != [12, 1]:
        raise AssertionError("fixed gate cost mismatch")
    if analysis["policy"]["expected_cost"] != [382, 75]:
        raise AssertionError("adaptive gate cost mismatch")

    postselection = post_selection_counterexample()
    certificate_payload = {
        "factor_A": factor_a,
        "factor_B": factor_b,
        "sequential": sequential,
        "postselection": postselection,
        "gate_certificate_sha256": gate_certificate["sha256"],
    }
    certificate = {
        "payload": certificate_payload,
        "sha256": sha256(
            canonical_json(certificate_payload).encode("utf-8")
        ).hexdigest(),
    }
    tampered = copy.deepcopy(certificate)
    tampered["payload"]["sequential"]["null_b"][
        "terminal_expectation"
    ] = [2, 1]
    tamper_rejected = (
        sha256(
            canonical_json(tampered["payload"]).encode("utf-8")
        ).hexdigest()
        != tampered["sha256"]
    )
    if not tamper_rejected:
        raise AssertionError("tampered public certificate was accepted")

    report = {
        "schema": (
            "inference-power-compiler/"
            "adaptive-eprocess-public-independent-replay/1"
        ),
        "private_report_sha256": (
            "382855262c1226d97113d4d78853765571bc0732d394d379fd3069078bfaf543"
        ),
        "composite_factors": {
            "A": factor_a,
            "B": factor_b,
        },
        "predictable_adaptation": {
            "policy": {
                "low": "A",
                "high": "B",
                "switch_above": [1, 1],
            },
            "horizon": 4,
            "threshold": [9, 1],
            "alpha_bound": [1, 9],
            "worlds": sequential,
        },
        "post_selection_counterexample": postselection,
        "logic_power_v10_gate_replay": {
            "hypotheses": 128,
            "conflict_pairs": len(analysis["conflict_pairs"]),
            "fixed_basis_cost": analysis["fixed_basis_cost"],
            "clean_path": order,
            "adaptive_expected_cost": analysis["policy"]["expected_cost"],
            "certificate_sha256": gate_certificate["sha256"],
        },
        "public_certificate": {
            "sha256": certificate["sha256"],
            "tampered_rejected": tamper_rejected,
        },
        "agreement_with_private_report": "PASS",
    }
    report["sha256"] = sha256(
        canonical_json(report).encode("utf-8")
    ).hexdigest()
    path = ROOT / "ADAPTIVE_EPROCESS_PUBLIC_REPLAY.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
