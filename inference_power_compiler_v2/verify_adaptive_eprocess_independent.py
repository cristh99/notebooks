from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from typing import Sequence

F = Fraction
ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def solve_square(
    matrix: Sequence[Sequence[Fraction]], rhs: Sequence[Fraction]
) -> list[Fraction] | None:
    n = len(matrix)
    augmented = [list(map(F, matrix[i])) + [F(rhs[i])] for i in range(n)]
    for column in range(n):
        pivot = next(
            (row for row in range(column, n) if augmented[row][column]),
            None,
        )
        if pivot is None:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            scale = augmented[row][column]
            if scale:
                augmented[row] = [
                    augmented[row][i] - scale * augmented[column][i]
                    for i in range(n + 1)
                ]
    return [augmented[i][-1] for i in range(n)]


def synthesize(
    null_laws: tuple[tuple[Fraction, Fraction], ...],
    alternative_laws: tuple[tuple[Fraction, Fraction], ...],
) -> dict[str, object]:
    # Variables are factor(0), factor(1), and the guaranteed alternative mean g.
    constraints: list[tuple[tuple[Fraction, ...], Fraction, str]] = [
        ((F(1), F(0), F(0)), F(0), "factor[0]=0"),
        ((F(0), F(1), F(0)), F(0), "factor[1]=0"),
    ]
    constraints += [
        ((law[0], law[1], F(0)), F(1), f"null[{i}]=1")
        for i, law in enumerate(null_laws)
    ]
    constraints += [
        ((law[0], law[1], F(-1)), F(0), f"alternative[{i}]=g")
        for i, law in enumerate(alternative_laws)
    ]

    best: tuple[Fraction, tuple[Fraction, Fraction], tuple[int, ...]] | None = None
    examined = 0
    feasible = 0
    for active in combinations(range(len(constraints)), 3):
        examined += 1
        solution = solve_square(
            [constraints[index][0] for index in active],
            [constraints[index][1] for index in active],
        )
        if solution is None:
            continue
        f0, f1, g = solution
        if f0 < 0 or f1 < 0:
            continue
        null_means = tuple(law[0] * f0 + law[1] * f1 for law in null_laws)
        alt_means = tuple(
            law[0] * f0 + law[1] * f1 for law in alternative_laws
        )
        if any(mean > 1 for mean in null_means):
            continue
        if any(mean < g for mean in alt_means):
            continue
        feasible += 1
        candidate = (g, (f0, f1), active)
        if best is None or g > best[0] or (g == best[0] and (f0, f1) < best[1]):
            best = candidate
    if best is None:
        raise AssertionError("no exact factor vertex found")
    g, factor, active = best
    null_means = tuple(law[0] * factor[0] + law[1] * factor[1] for law in null_laws)
    alt_means = tuple(
        law[0] * factor[0] + law[1] * factor[1]
        for law in alternative_laws
    )
    return {
        "factor": [q(factor[0]), q(factor[1])],
        "gamma": q(g),
        "null_means": [q(value) for value in null_means],
        "alternative_means": [q(value) for value in alt_means],
        "active": [constraints[index][2] for index in active],
        "vertices_examined": examined,
        "feasible_vertices": feasible,
    }


LAWS = {
    "A": {
        "null_a": (F(3, 4), F(1, 4)),
        "null_b": (F(2, 3), F(1, 3)),
        "alt_a": (F(1, 4), F(3, 4)),
        "alt_b": (F(1, 3), F(2, 3)),
    },
    "B": {
        "null_a": (F(1, 4), F(3, 4)),
        "null_b": (F(1, 3), F(2, 3)),
        "alt_a": (F(3, 4), F(1, 4)),
        "alt_b": (F(2, 3), F(1, 3)),
    },
}


FACTORS = {
    "A": (F(0), F(3)),
    "B": (F(3), F(0)),
}


def enumerate_world(world: str) -> dict[str, object]:
    terminal: list[tuple[Fraction, Fraction, str]] = []

    def walk(depth: int, probability: Fraction, e_value: Fraction) -> None:
        if e_value >= 9:
            terminal.append((probability, e_value, "threshold"))
            return
        if depth > 0 and e_value == 0:
            terminal.append((probability, e_value, "ruin"))
            return
        if depth == 4:
            terminal.append((probability, e_value, "horizon"))
            return
        experiment = "A" if e_value <= 1 else "B"
        for outcome in (0, 1):
            step_probability = LAWS[experiment][world][outcome]
            if step_probability:
                walk(
                    depth + 1,
                    probability * step_probability,
                    e_value * FACTORS[experiment][outcome],
                )

    walk(0, F(1), F(1))
    mass = sum((probability for probability, _e, _r in terminal), F(0))
    expectation = sum(
        (probability * e_value for probability, e_value, _r in terminal), F(0)
    )
    crossing = sum(
        (probability for probability, _e, reason in terminal if reason == "threshold"),
        F(0),
    )
    if mass != 1:
        raise AssertionError("terminal prefixes do not partition the law")
    return {
        "mass": q(mass),
        "expectation": q(expectation),
        "crossing": q(crossing),
        "terminal_prefixes": len(terminal),
    }


def verify_receipt(receipt: dict[str, object]) -> list[str]:
    payload = receipt.get("payload")
    claimed = receipt.get("sha256")
    if not isinstance(payload, dict) or not isinstance(claimed, str):
        return ["shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    return []


def main() -> None:
    factor_a = synthesize(
        (LAWS["A"]["null_a"], LAWS["A"]["null_b"]),
        (LAWS["A"]["alt_a"], LAWS["A"]["alt_b"]),
    )
    factor_b = synthesize(
        (LAWS["B"]["null_a"], LAWS["B"]["null_b"]),
        (LAWS["B"]["alt_a"], LAWS["B"]["alt_b"]),
    )
    assert factor_a["factor"] == [[0, 1], [3, 1]]
    assert factor_b["factor"] == [[3, 1], [0, 1]]
    assert factor_a["gamma"] == [2, 1]
    assert factor_b["gamma"] == [2, 1]

    worlds = {world: enumerate_world(world) for world in ("null_a", "null_b", "alt_a", "alt_b")}
    expected = {
        "null_a": ([9, 16], [1, 16]),
        "null_b": ([1, 1], [1, 9]),
        "alt_a": ([81, 16], [9, 16]),
        "alt_b": ([4, 1], [4, 9]),
    }
    for world, (expectation, crossing) in expected.items():
        assert worlds[world]["expectation"] == expectation
        assert worlds[world]["crossing"] == crossing
    for world in ("null_a", "null_b"):
        assert F(*worlds[world]["expectation"]) <= 1
        assert F(*worlds[world]["crossing"]) <= F(1, 9)

    factor = (F(1, 2), F(3, 2))
    posthoc = sum(
        (F(1, 4) * max(factor[left], factor[right]) for left in (0, 1) for right in (0, 1)),
        F(0),
    )
    predictable_average = sum(
        (F(1, 4) * (factor[left] + factor[right]) / 2 for left in (0, 1) for right in (0, 1)),
        F(0),
    )
    assert posthoc == F(5, 4)
    assert predictable_average == 1

    payload = {
        "schema": "adaptive-eprocess-independent-public-verification/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "branch": "agent/inference-power-compiler-v2-logic-power-v10",
            "pull_request": 68,
            "head": "76c0eb4b1f7e703cdd7a38eacc8ba22fcd83d597",
            "adaptive_source_blob": "9b89e2672491af2d61738fb10c6b74d1e6caaa26",
            "private_report_sha256": "382855262c1226d97113d4d78853765571bc0732d394d379fd3069078bfaf543",
        },
        "factors": {"A": factor_a, "B": factor_b},
        "adaptive_worlds": worlds,
        "post_selection": {
            "posthoc_maximum_mean": q(posthoc),
            "predictable_average_mean": q(predictable_average),
        },
        "gates": {
            "exact_rational_lp": "PASS",
            "all_null_worlds": "PASS",
            "terminal_prefix_partition": "PASS",
            "optional_stopping_bound": "PASS",
            "alternative_growth": "PASS",
            "post_selection_falsifier": "PASS",
        },
    }
    receipt = {"payload": payload, "sha256": digest(payload)}
    assert verify_receipt(receipt) == []
    tampered = deepcopy(receipt)
    tampered["payload"]["adaptive_worlds"]["null_b"]["expectation"] = [2, 1]
    assert verify_receipt(tampered) == ["payload-hash"]

    output = ROOT / "ADAPTIVE_EPROCESS_PUBLIC_RECEIPT.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
