from __future__ import annotations

from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def matrix_multiply(left, right):
    return tuple(
        tuple(
            sum((left[i][k] * right[k][j] for k in range(len(right))), Fraction(0))
            for j in range(len(right[0]))
        )
        for i in range(len(left))
    )


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> None:
    identity = ((Fraction(1), Fraction(0)), (Fraction(0), Fraction(1)))
    quarter = ((Fraction(3, 4), Fraction(1, 4)), (Fraction(1, 4), Fraction(3, 4)))
    three_eighths = ((Fraction(5, 8), Fraction(3, 8)), (Fraction(3, 8), Fraction(5, 8)))

    forward = matrix_multiply(identity, quarter)
    if forward != quarter:
        raise AssertionError("forward garbling failed")
    if any(sum(row, Fraction(0)) != 1 or any(x < 0 for x in row) for row in quarter):
        raise AssertionError("kernel is not stochastic")

    # Reverse equations for K=[[a,1-a],[b,1-b]] are
    # 3a+b=4 and a+3b=0. Their unique solution violates nonnegativity.
    b = Fraction(-1, 2)
    a = Fraction(3, 2)
    if 3 * a + b != 4 or a + 3 * b != 0:
        raise AssertionError("reverse linear system solution changed")
    if a >= 0 and b >= 0 and a <= 1 and b <= 1:
        raise AssertionError("reverse kernel unexpectedly stochastic")

    prior = (Fraction(1, 2), Fraction(1, 2))
    payoff = ((Fraction(4), Fraction(0)), (Fraction(-4), Fraction(0)))
    target_identity_payoff = sum(
        (prior[state] * identity[state][outcome] * payoff[state][outcome]
         for state in range(2) for outcome in range(2)),
        Fraction(0),
    )
    source_rule_payoffs = []
    for mapping in product(range(2), repeat=2):
        value = sum(
            (
                prior[state]
                * quarter[state][source_outcome]
                * payoff[state][mapping[source_outcome]]
                for state in range(2)
                for source_outcome in range(2)
            ),
            Fraction(0),
        )
        source_rule_payoffs.append(value)
    if target_identity_payoff != 2:
        raise AssertionError("target payoff changed")
    if tuple(source_rule_payoffs) != (Fraction(0), Fraction(1), Fraction(-1), Fraction(0)):
        raise AssertionError("source rule payoffs changed")
    if target_identity_payoff - max(source_rule_payoffs) != 1:
        raise AssertionError("separating gap changed")

    composed = matrix_multiply(quarter, quarter)
    if composed != three_eighths:
        raise AssertionError("Blackwell transitivity control changed")

    payload = {
        "schema": "blackwell-compiler/public-independent-receipt/1",
        "private_repository": "cristh99/my_first_repository",
        "private_pr": 68,
        "private_source_blob": "b4f24a4aa004500d7eda6fb0a066124d0d4fdee5",
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "forward_kernel": [[[3, 4], [1, 4]], [[1, 4], [3, 4]]],
        "reverse_linear_solution": {"a": [3, 2], "b": [-1, 2], "stochastic": False},
        "decision_witness": {
            "payoff": [[[4, 1], [0, 1]], [[-4, 1], [0, 1]]],
            "target_identity_payoff": [2, 1],
            "source_rule_payoffs": [[0, 1], [1, 1], [-1, 1], [0, 1]],
            "gap": [1, 1],
        },
        "transitivity": {
            "quarter_composed_quarter": [[[5, 8], [3, 8]], [[3, 8], [5, 8]]],
            "pass": True,
        },
        "gates": {
            "forward_kernel_replay": "PASS",
            "reverse_infeasibility": "PASS",
            "decision_separator": "PASS",
            "transitivity": "PASS",
        },
    }
    receipt = {
        "payload": payload,
        "sha256": sha256(canonical_json(payload).encode()).hexdigest(),
    }
    path = ROOT / "BLACKWELL_PUBLIC_RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
