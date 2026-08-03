from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def canonical(x: object) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def digest(x: object) -> str:
    return sha256(canonical(x).encode()).hexdigest()


def q(x: F) -> list[int]:
    return [x.numerator, x.denominator]


def verify_receipt(receipt: dict[str, object]) -> list[str]:
    payload = receipt.get("payload")
    claimed = receipt.get("sha256")
    if not isinstance(payload, dict) or not isinstance(claimed, str):
        return ["shape"]
    return [] if digest(payload) == claimed else ["payload-hash"]


def main() -> None:
    worlds: list[dict[str, object]] = []
    for treatment in product((0, 1), repeat=2):
        for outcome in product((0, 1), repeat=4):
            name = "A" + "".join(map(str, treatment)) + "_Y" + "".join(map(str, outcome))
            obs = [F(0) for _ in range(4)]
            do0 = [F(0), F(0)]
            do1 = [F(0), F(0)]
            for u in (0, 1):
                a = treatment[u]
                y = outcome[2 * a + u]
                obs[2 * a + y] += F(1, 2)
                do0[outcome[u]] += F(1, 2)
                do1[outcome[2 + u]] += F(1, 2)
            ace = do1[1] - do0[1]
            worlds.append(
                {
                    "name": name,
                    "obs": tuple(obs),
                    "do0": tuple(do0),
                    "do1": tuple(do1),
                    "ace": ace,
                    "positive": ace > 0,
                }
            )

    by_name = {world["name"]: world for world in worlds}
    conflicts = [
        (left, right)
        for left, right in combinations(worlds, 2)
        if left["positive"] != right["positive"]
    ]
    observational_conflicts = [
        pair for pair in conflicts if pair[0]["obs"] == pair[1]["obs"]
    ]
    assert len(worlds) == 64
    assert sum(bool(world["positive"]) for world in worlds) == 20
    assert len(conflicts) == 880
    assert len(observational_conflicts) == 66
    first_obstruction = tuple(world["name"] for world in observational_conflicts[0])
    assert first_obstruction == ("A00_Y0000", "A00_Y0001")

    def separates(pair: tuple[dict[str, object], dict[str, object]], key: str) -> bool:
        return pair[0][key] != pair[1][key]

    assert any(not separates(pair, "do0") for pair in conflicts)
    assert any(not separates(pair, "do1") for pair in conflicts)
    assert all(separates(pair, "do0") or separates(pair, "do1") for pair in conflicts)

    groups: dict[tuple[F, F], list[dict[str, object]]] = {}
    for world in worlds:
        groups.setdefault(world["do0"], []).append(world)
    branch_summary = []
    unresolved = 0
    for law, group in sorted(groups.items()):
        values = sorted({bool(world["positive"]) for world in group})
        needs_do1 = len(values) > 1
        if needs_do1:
            unresolved += len(group)
        branch_summary.append(
            {
                "do0_law": [q(value) for value in law],
                "worlds": len(group),
                "target_values": values,
                "requires_do1": needs_do1,
            }
        )
    assert unresolved == 48
    fixed_cost = F(6)
    adaptive_expected = F(3) + F(unresolved, len(worlds)) * 3
    assert adaptive_expected == F(21, 4)

    histogram: dict[str, int] = {}
    for world in worlds:
        value = world["ace"]
        key = f"{value.numerator}/{value.denominator}"
        histogram[key] = histogram.get(key, 0) + 1
    assert histogram == {"0/1": 24, "1/2": 16, "1/1": 4, "-1/2": 16, "-1/1": 4}

    payload = {
        "schema": "finite-scm-independent-public-verification/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": "d8ebcc960109f426ed3aa4a1b480587cfc95bac0",
            "source_blob": "0e5d1466703a983df672d0330d3f51a75dced8b1",
        },
        "family": {
            "worlds": len(worlds),
            "positive_effect_worlds": 20,
            "nonpositive_effect_worlds": 44,
            "ace_histogram": dict(sorted(histogram.items())),
        },
        "identification": {
            "truth_conflicting_pairs": len(conflicts),
            "observation_only_conflicts": len(observational_conflicts),
            "first_obstruction": list(first_obstruction),
            "minimum_fixed_basis": ["do_A_0", "do_A_1"],
            "fixed_cost": q(fixed_cost),
            "adaptive_first_experiment": "do_A_0",
            "adaptive_expected_cost": q(adaptive_expected),
            "adaptive_worst_cost": [6, 1],
            "expected_reduction": [3, 4],
            "do0_branches": branch_summary,
        },
        "gates": {
            "complete_scm_enumeration": "PASS",
            "observation_impossibility": "PASS",
            "intervention_separation": "PASS",
            "fixed_basis_minimality": "PASS",
            "adaptive_cost": "PASS",
        },
    }
    receipt = {"payload": payload, "sha256": digest(payload)}
    assert verify_receipt(receipt) == []
    tampered = deepcopy(receipt)
    tampered["payload"]["identification"]["adaptive_expected_cost"] = [0, 1]
    assert verify_receipt(tampered) == ["payload-hash"]
    (ROOT / "FINITE_SCM_PUBLIC_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
