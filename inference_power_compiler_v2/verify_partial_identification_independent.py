from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
from itertools import product
from collections import defaultdict
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


def width(group: list[dict[str, object]]) -> F:
    values = [world["ace"] for world in group]
    return max(values) - min(values)


def conditional_expected_width(
    group: list[dict[str, object]], key: str
) -> tuple[F, F]:
    parts: dict[tuple[F, ...], list[dict[str, object]]] = defaultdict(list)
    for world in group:
        parts[world[key]].append(world)
    expected = sum((F(len(part), len(group)) * width(part) for part in parts.values()), F(0))
    worst = max(width(part) for part in parts.values())
    return expected, worst


def main() -> None:
    worlds: list[dict[str, object]] = []
    for treatment in product((0, 1), repeat=2):
        for outcome in product((0, 1), repeat=4):
            name = "A" + "".join(map(str, treatment)) + "_Y" + "".join(map(str, outcome))
            obs = [F(0)] * 4
            do0 = [F(0), F(0)]
            do1 = [F(0), F(0)]
            for u in (0, 1):
                a = treatment[u]
                y = outcome[2 * a + u]
                obs[2 * a + y] += F(1, 2)
                do0[outcome[u]] += F(1, 2)
                do1[outcome[2 + u]] += F(1, 2)
            worlds.append(
                {
                    "name": name,
                    "obs": tuple(obs),
                    "do0": tuple(do0),
                    "do1": tuple(do1),
                    "ace": do1[1] - do0[1],
                }
            )

    obs_groups: dict[tuple[F, ...], list[dict[str, object]]] = defaultdict(list)
    for world in worlds:
        obs_groups[world["obs"]].append(world)
    assert len(obs_groups) == 10
    assert all(width(group) == 1 for group in obs_groups.values())

    observation_expected = sum((F(len(group), 64) * width(group) for group in obs_groups.values()), F(0))
    fixed_do0 = F(0)
    fixed_do1 = F(0)
    adaptive = F(0)
    selected_strata = {"do0": 0, "do1": 0}
    selected_worlds = {"do0": 0, "do1": 0}
    point_identified = 0
    half_width = 0
    strata = []

    for observation, group in sorted(obs_groups.items()):
        do0 = conditional_expected_width(group, "do0")
        do1 = conditional_expected_width(group, "do1")
        fixed_do0 += F(len(group), 64) * do0[0]
        fixed_do1 += F(len(group), 64) * do1[0]
        selected = min((do0[1], do0[0], "do0"), (do1[1], do1[0], "do1"))
        name = selected[2]
        selected_strata[name] += 1
        selected_worlds[name] += len(group)
        adaptive += F(len(group), 64) * selected[1]
        if selected[1] == 0:
            point_identified += len(group)
        elif selected[1] == F(1, 2):
            half_width += len(group)
        else:
            raise AssertionError("unexpected adaptive width")
        values = sorted({world["ace"] for world in group})
        strata.append(
            {
                "observational_law": [q(value) for value in observation],
                "worlds": len(group),
                "identified_values": [q(value) for value in values],
                "sharp_interval": [q(values[0]), q(values[-1])],
                "width": q(values[-1] - values[0]),
                "selected_intervention": name,
                "selected_expected_width": q(selected[1]),
            }
        )

    both: dict[tuple[tuple[F, ...], tuple[F, ...], tuple[F, ...]], list[dict[str, object]]] = defaultdict(list)
    for world in worlds:
        both[(world["obs"], world["do0"], world["do1"])].append(world)
    assert all(width(group) == 0 for group in both.values())
    assert observation_expected == 1
    assert fixed_do0 == fixed_do1 == F(1, 2)
    assert adaptive == F(1, 4)
    assert selected_strata == {"do0": 7, "do1": 3}
    assert selected_worlds == {"do0": 48, "do1": 16}
    assert point_identified == 32 and half_width == 32

    payload = {
        "schema": "partial-identification-independent-public-verification/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "partial_identification_source_commit": "fb5cda9602b872702d35ce851ae0b8b6869fa189",
            "run_source_commit": "0642d0e19b39bd07986ab5db03debae55254f3ed",
        },
        "frontier": {
            "worlds": 64,
            "observational_strata": 10,
            "observation_only_expected_width": q(observation_expected),
            "fixed_do0_expected_width": q(fixed_do0),
            "fixed_do1_expected_width": q(fixed_do1),
            "adaptive_one_intervention_expected_width": q(adaptive),
            "both_interventions_expected_width": [0, 1],
            "adaptive_selected_strata": selected_strata,
            "adaptive_selected_worlds": selected_worlds,
            "point_identified_worlds": point_identified,
            "half_width_worlds": half_width,
        },
        "strata": strata,
        "gates": {
            "complete_world_enumeration": "PASS",
            "sharp_observational_sets": "PASS",
            "fixed_intervention_frontier": "PASS",
            "adaptive_intervention_policy": "PASS",
            "point_identification_with_both": "PASS",
        },
    }
    receipt = {"payload": payload, "sha256": digest(payload)}
    assert verify_receipt(receipt) == []
    tampered = deepcopy(receipt)
    tampered["payload"]["frontier"]["adaptive_one_intervention_expected_width"] = [0, 1]
    assert verify_receipt(tampered) == ["payload-hash"]
    (ROOT / "PARTIAL_IDENTIFICATION_PUBLIC_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
