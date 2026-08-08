from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def q(x: F) -> list[int]:
    return [x.numerator, x.denominator]


def canonical(x: object) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def digest(x: object) -> str:
    return sha256(canonical(x).encode()).hexdigest()


def total_variation(p: tuple[F, ...], r: tuple[F, ...]) -> F:
    assert len(p) == len(r)
    assert sum(p, F(0)) == 1 and sum(r, F(0)) == 1
    return sum((abs(a - b) for a, b in zip(p, r)), F(0)) / 2


def bits(d: int) -> tuple[str, ...]:
    return tuple("".join(map(str, x)) for x in product((0, 1), repeat=d))


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b))


def bsc_law(world: str, outcomes: tuple[str, ...], crossover: F) -> tuple[F, ...]:
    d = len(world)
    return tuple(
        crossover ** hamming(world, outcome)
        * (1 - crossover) ** (d - hamming(world, outcome))
        for outcome in outcomes
    )


def mixture(worlds: tuple[str, ...], laws: dict[str, tuple[F, ...]]) -> tuple[F, ...]:
    weight = F(1, len(worlds))
    return tuple(
        sum((weight * laws[world][index] for world in worlds), F(0))
        for index in range(len(next(iter(laws.values()))))
    )


def verify_receipt(receipt: dict[str, object]) -> list[str]:
    payload = receipt.get("payload")
    claimed = receipt.get("sha256")
    if not isinstance(payload, dict) or not isinstance(claimed, str):
        return ["shape"]
    return [] if digest(payload) == claimed else ["payload-hash"]


def main() -> None:
    # Le Cam: target separation one, TV one half.
    p0 = (F(3, 4), F(1, 4))
    p1 = (F(1, 4), F(3, 4))
    tv = total_variation(p0, p1)
    le_cam = F(1) * (1 - tv) / 8
    assert tv == F(1, 2) and le_cam == F(1, 16)

    # Assouad: d=4 binary symmetric channel with crossover 1/4.
    d, crossover = 4, F(1, 4)
    worlds = outcomes = bits(d)
    laws = {world: bsc_law(world, outcomes, crossover) for world in worlds}
    coordinate_tvs: list[F] = []
    lower = F(0)
    for coordinate in range(d):
        zero = tuple(world for world in worlds if world[coordinate] == "0")
        one = tuple(world for world in worlds if world[coordinate] == "1")
        coord_tv = total_variation(mixture(zero, laws), mixture(one, laws))
        coordinate_tvs.append(coord_tv)
        lower += (1 - coord_tv) / 2
    identity_risks = tuple(
        sum((laws[world][index] * hamming(world, outcome) for index, outcome in enumerate(outcomes)), F(0))
        for world in worlds
    )
    upper = max(identity_risks)
    assert coordinate_tvs == [F(1, 2)] * 4
    assert lower == 1 and upper == 1

    payload = {
        "schema": "lower-bound-independent-public-verification/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "branch": "agent/inference-power-compiler-v2-logic-power-v10",
            "pull_request": 68,
            "head": "0ab47387d36e0b624792607665ae447a300551cf",
            "lower_bound_source_blob": "715d2cc8bb23cba51ee73ce0cc0cb80c68d3a062",
        },
        "le_cam": {
            "total_variation": q(tv),
            "squared_target_separation": [1, 1],
            "compiled_lower_bound": q(le_cam),
        },
        "assouad": {
            "dimension": d,
            "crossover": q(crossover),
            "coordinate_total_variations": [q(value) for value in coordinate_tvs],
            "compiled_lower_bound": q(lower),
            "identity_decoder_upper_bound": q(upper),
            "matched_exact_minimax": lower == upper,
            "world_count": len(worlds),
            "outcome_count": len(outcomes),
        },
        "gates": {
            "exact_rational_laws": "PASS",
            "mixture_construction": "PASS",
            "le_cam_constant": "PASS",
            "assouad_coordinate_bounds": "PASS",
            "matching_upper_witness": "PASS",
        },
    }
    receipt = {"payload": payload, "sha256": digest(payload)}
    assert verify_receipt(receipt) == []
    tampered = deepcopy(receipt)
    tampered["payload"]["assouad"]["compiled_lower_bound"] = [0, 1]
    assert verify_receipt(tampered) == ["payload-hash"]
    (ROOT / "LOWER_BOUND_PUBLIC_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
