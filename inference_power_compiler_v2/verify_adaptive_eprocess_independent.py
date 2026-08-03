from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def q(x: F) -> list[int]:
    return [x.numerator, x.denominator]


def canonical(x: object) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def digest(x: object) -> str:
    return sha256(canonical(x).encode()).hexdigest()


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
FACTORS = {"A": (F(0), F(3)), "B": (F(3), F(0))}


def mean(law: tuple[F, F], factor: tuple[F, F]) -> F:
    return law[0] * factor[0] + law[1] * factor[1]


def verify_optimal_factors() -> dict[str, object]:
    # A: null_b gives 2 f0 + f1 <= 3. Since f0>=0,
    # f0+2 f1 <= 2(2 f0+f1) <= 6, so alt_b mean <=2.
    # B is the mirrored inequality. The displayed candidates attain 2.
    result: dict[str, object] = {}
    for experiment in ("A", "B"):
        factor = FACTORS[experiment]
        null_means = {
            world: mean(LAWS[experiment][world], factor)
            for world in ("null_a", "null_b")
        }
        alt_means = {
            world: mean(LAWS[experiment][world], factor)
            for world in ("alt_a", "alt_b")
        }
        assert max(null_means.values()) == 1
        assert min(alt_means.values()) == 2
        result[experiment] = {
            "factor": [q(factor[0]), q(factor[1])],
            "null_means": {world: q(value) for world, value in null_means.items()},
            "alternative_means": {world: q(value) for world, value in alt_means.items()},
            "optimal_worst_alternative_mean": [2, 1],
            "upper_bound_proof": "nonnegativity plus the tight least-favorable null inequality",
        }
    return result


def enumerate_world(world: str) -> dict[str, object]:
    terminal: list[tuple[F, F, str]] = []

    def walk(depth: int, probability: F, e_value: F) -> None:
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
            step = LAWS[experiment][world][outcome]
            if step:
                walk(depth + 1, probability * step, e_value * FACTORS[experiment][outcome])

    walk(0, F(1), F(1))
    mass = sum((p for p, _e, _r in terminal), F(0))
    expectation = sum((p * e for p, e, _r in terminal), F(0))
    crossing = sum((p for p, _e, r in terminal if r == "threshold"), F(0))
    assert mass == 1
    return {
        "terminal_mass": q(mass),
        "terminal_expectation": q(expectation),
        "threshold_crossing_probability": q(crossing),
        "terminal_prefixes": len(terminal),
    }


def verify_receipt(receipt: dict[str, object]) -> list[str]:
    payload = receipt.get("payload")
    claimed = receipt.get("sha256")
    if not isinstance(payload, dict) or not isinstance(claimed, str):
        return ["shape"]
    return [] if digest(payload) == claimed else ["payload-hash"]


def main() -> None:
    factors = verify_optimal_factors()
    worlds = {world: enumerate_world(world) for world in ("null_a", "null_b", "alt_a", "alt_b")}
    expected = {
        "null_a": ([9, 16], [1, 16]),
        "null_b": ([1, 1], [1, 9]),
        "alt_a": ([81, 16], [9, 16]),
        "alt_b": ([4, 1], [4, 9]),
    }
    for world, (expectation, crossing) in expected.items():
        assert worlds[world]["terminal_expectation"] == expectation
        assert worlds[world]["threshold_crossing_probability"] == crossing
    for world in ("null_a", "null_b"):
        assert F(*worlds[world]["terminal_expectation"]) <= 1
        assert F(*worlds[world]["threshold_crossing_probability"]) <= F(1, 9)

    factor = (F(1, 2), F(3, 2))
    posthoc = sum((F(1, 4) * max(factor[i], factor[j]) for i in (0, 1) for j in (0, 1)), F(0))
    predictable = sum((F(1, 4) * (factor[i] + factor[j]) / 2 for i in (0, 1) for j in (0, 1)), F(0))
    assert posthoc == F(5, 4) and predictable == 1

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
        "factor_optimality": factors,
        "adaptive_worlds": worlds,
        "post_selection_falsifier": {
            "predictable_average_mean": q(predictable),
            "posthoc_maximum_mean": q(posthoc),
            "inflation": q(posthoc - 1),
        },
        "gates": {
            "exact_rational_factor_proof": "PASS",
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
    tampered["payload"]["adaptive_worlds"]["null_b"]["terminal_expectation"] = [2, 1]
    assert verify_receipt(tampered) == ["payload-hash"]

    (ROOT / "ADAPTIVE_EPROCESS_PUBLIC_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
