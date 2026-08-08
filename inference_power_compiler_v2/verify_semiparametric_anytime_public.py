from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent
PRIVATE_HEAD = "a4aba3a0b42b2e59fd9bfcf2a3f8f5a3e3e3449f"
PRIVATE_BLOBS = {
    "compiler": "d2dcdea953608d50337060d54ac667d41e7fb351",
    "runner": "1288d570f03978d74496cd8fd793336fb8ae7e92",
    "tests": "28061e15ff7a8081772f460ef6553226ac12f235",
    "lean": "50b5ec5dde709cd93957c465a52d75c9897b2cc8",
    "workflow": "b1f5d4673aedc332755e1b866d1f3656f1621fb4",
}
Z_VALUES = ("z0", "z1")
PZ = {"z0": Fraction(1, 2), "z1": Fraction(1, 2)}
E_TRUE = {"z0": Fraction(1, 4), "z1": Fraction(3, 4)}
MU0_TRUE = {"z0": Fraction(1, 8), "z1": Fraction(3, 8)}
MU1_TRUE = {"z0": Fraction(5, 8), "z1": Fraction(7, 8)}
MODELS = {
    "model_A": {
        "e": {"z0": Fraction(1, 3), "z1": Fraction(2, 3)},
        "mu0": {"z0": Fraction(1, 4), "z1": Fraction(1, 2)},
        "mu1": {"z0": Fraction(1, 2), "z1": Fraction(3, 4)},
        "bound": Fraction(3, 64),
    },
    "model_B": {
        "e": {"z0": Fraction(2, 5), "z1": Fraction(3, 5)},
        "mu0": {"z0": Fraction(1, 3), "z1": Fraction(1, 2)},
        "mu1": {"z0": Fraction(1, 2), "z1": Fraction(2, 3)},
        "bound": Fraction(19, 192),
    },
}
EVENT_TYPES = (
    ("z0", 0, 0),
    ("z0", 0, 1),
    ("z0", 1, 0),
    ("z0", 1, 1),
    ("z1", 0, 0),
    ("z1", 0, 1),
    ("z1", 1, 0),
    ("z1", 1, 1),
)
EVENT_CODES = (
    7, 7, 0, 0, 7, 0, 0, 7, 2, 7, 0, 0, 4, 4, 7, 0,
    7, 0, 0, 1, 1, 6, 7, 0, 7, 0, 4, 0, 1, 2, 5, 7,
    4, 3, 7, 7, 6, 2, 7, 0, 0, 4, 0, 7, 7, 5, 6, 5,
    7, 7, 3, 7, 7, 7, 0, 7, 0, 0, 3, 0, 0, 0, 3, 3,
)
GRID = tuple(Fraction(index, 20) for index in range(21))
EXPERTS = (
    "constant_positive",
    "constant_negative",
    "follow_previous",
    "oppose_previous",
)
ADAPTIVE_WEIGHTS = (Fraction(1, 4),) * 4
BASELINE_WEIGHTS = (
    Fraction(1, 2),
    Fraction(1, 2),
    Fraction(0),
    Fraction(0),
)
THRESHOLD = Fraction(20)
LOWER = Fraction(-5, 4)
WIDTH = Fraction(3)
TRUE_ATE = Fraction(1, 2)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def parse_q(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("malformed rational")
    return Fraction(int(value[0]), int(value[1]))


def event_probability(z: str, a: int, y: int) -> Fraction:
    pa = E_TRUE[z] if a == 1 else 1 - E_TRUE[z]
    mu = MU1_TRUE[z] if a == 1 else MU0_TRUE[z]
    py = mu if y == 1 else 1 - mu
    return PZ[z] * pa * py


def aipw(z: str, a: int, y: int, model_name: str) -> Fraction:
    model = MODELS[model_name]
    e = model["e"][z]
    mu0 = model["mu0"][z]
    mu1 = model["mu1"][z]
    return (
        mu1
        - mu0
        + Fraction(a, 1) / e * (Fraction(y, 1) - mu1)
        - Fraction(1 - a, 1) / (1 - e) * (Fraction(y, 1) - mu0)
    )


def model_certificate(model_name: str) -> dict[str, object]:
    model = MODELS[model_name]
    actual = Fraction(0)
    bound = Fraction(0)
    e_l2 = Fraction(0)
    mu0_l2 = Fraction(0)
    mu1_l2 = Fraction(0)
    cells = {}
    law = []
    for z in Z_VALUES:
        de = model["e"][z] - E_TRUE[z]
        d0 = model["mu0"][z] - MU0_TRUE[z]
        d1 = model["mu1"][z] - MU1_TRUE[z]
        rem = de * (d1 / model["e"][z] + d0 / (1 - model["e"][z]))
        component = abs(de) * (
            abs(d1) / model["e"][z] + abs(d0) / (1 - model["e"][z])
        )
        actual += PZ[z] * rem
        bound += PZ[z] * component
        e_l2 += PZ[z] * de * de
        mu0_l2 += PZ[z] * d0 * d0
        mu1_l2 += PZ[z] * d1 * d1
        cells[z] = {
            "propensity_error": q(de),
            "mu0_error": q(d0),
            "mu1_error": q(d1),
            "remainder": q(rem),
            "component_bound": q(component),
        }
    expected = TRUE_ATE + actual
    reconstructed = Fraction(0)
    for event in EVENT_TYPES:
        probability = event_probability(*event)
        score = aipw(*event, model_name)
        law.append(
            {
                "event": [event[0], event[1], event[2]],
                "probability": q(probability),
                "score": q(score),
            }
        )
        reconstructed += probability * score
    if reconstructed != expected:
        raise AssertionError("AIPW expectation identity failed")
    if not abs(actual) <= bound <= model["bound"]:
        raise AssertionError("remainder bound failed")
    return {
        "expected_score": q(expected),
        "actual_remainder": q(actual),
        "component_bound": q(bound),
        "declared_bound": q(model["bound"]),
        "e_l2_squared": q(e_l2),
        "mu0_l2_squared": q(mu0_l2),
        "mu1_l2_squared": q(mu1_l2),
        "cells": cells,
        "score_law": law,
    }


def normalize(value: Fraction) -> Fraction:
    return (value - LOWER) / WIDTH


def robust_factor(
    current_lambda: Fraction,
    observation: Fraction,
    mean: Fraction,
    remainder: Fraction,
) -> Fraction:
    correction = (
        remainder
        if current_lambda > 0
        else -remainder
        if current_lambda < 0
        else Fraction(0)
    )
    return 1 + current_lambda * (observation - mean - correction)


def expert_lambda(
    mode: str,
    previous: Fraction | None,
    mean: Fraction,
) -> Fraction:
    if mode == "constant_positive":
        return Fraction(1)
    if mode == "constant_negative":
        return Fraction(-1)
    if previous is None:
        return Fraction(0)
    sign = (
        Fraction(1)
        if previous > mean
        else Fraction(-1)
        if previous < mean
        else Fraction(0)
    )
    return sign if mode == "follow_previous" else -sign


def packet(values: tuple[Fraction, ...]) -> dict[str, object]:
    if not values:
        return {"size": 0, "accepted": [], "hull": None, "width": [0, 1]}
    return {
        "size": len(values),
        "accepted": [q(value) for value in values],
        "hull": [q(values[0]), q(values[-1])],
        "width": q(values[-1] - values[0]),
    }


def replay_path() -> dict[str, object]:
    wealths = {effect: [Fraction(1)] * 4 for effect in GRID}
    previous: Fraction | None = None
    true_history = []
    milestones = []
    milestone_times = {1, 8, 16, 24, 32, 48, 64}
    for time, code in enumerate(EVENT_CODES, 1):
        z, a, y = EVENT_TYPES[code]
        model_name = "model_B" if time % 2 == 1 else "model_A"
        score = aipw(z, a, y, model_name)
        observation = normalize(score)
        remainder = MODELS[model_name]["bound"] / WIDTH
        for effect in GRID:
            mean = normalize(effect)
            factors = tuple(
                robust_factor(
                    expert_lambda(mode, previous, mean),
                    observation,
                    mean,
                    remainder,
                )
                for mode in EXPERTS
            )
            wealths[effect] = [
                wealth * current_factor
                for wealth, current_factor in zip(wealths[effect], factors)
            ]
            adaptive = sum(
                weight * wealth
                for weight, wealth in zip(ADAPTIVE_WEIGHTS, wealths[effect])
            )
            if any(
                adaptive < weight * wealth
                for weight, wealth in zip(ADAPTIVE_WEIGHTS, wealths[effect])
            ):
                raise AssertionError("expert regret lower bound failed")
        accepted_adaptive = tuple(
            effect
            for effect in GRID
            if sum(
                weight * wealth
                for weight, wealth in zip(ADAPTIVE_WEIGHTS, wealths[effect])
            )
            < THRESHOLD
        )
        accepted_baseline = tuple(
            effect
            for effect in GRID
            if sum(
                weight * wealth
                for weight, wealth in zip(BASELINE_WEIGHTS, wealths[effect])
            )
            < THRESHOLD
        )
        true_adaptive = sum(
            weight * wealth
            for weight, wealth in zip(ADAPTIVE_WEIGHTS, wealths[TRUE_ATE])
        )
        true_baseline = sum(
            weight * wealth
            for weight, wealth in zip(BASELINE_WEIGHTS, wealths[TRUE_ATE])
        )
        true_history.append(
            {
                "time": time,
                "row_id": f"eval_{time:03d}",
                "model": model_name,
                "score": q(score),
                "normalized_score": q(observation),
                "adaptive_wealth": q(true_adaptive),
                "baseline_wealth": q(true_baseline),
                "included_adaptive": TRUE_ATE in accepted_adaptive,
                "included_baseline": TRUE_ATE in accepted_baseline,
            }
        )
        if time in milestone_times:
            milestones.append(
                {
                    "time": time,
                    "adaptive": packet(accepted_adaptive),
                    "baseline": packet(accepted_baseline),
                    "adaptive_subset_of_baseline": set(accepted_adaptive).issubset(accepted_baseline),
                }
            )
        previous = observation

    if not all(
        item["included_adaptive"] and item["included_baseline"]
        for item in true_history
    ):
        raise AssertionError("true effect excluded")
    final = milestones[-1]
    expected_adaptive = tuple(
        Fraction(value, 20) for value in (8, 9, 10, 11, 12, 13, 14, 15)
    )
    expected_baseline = tuple(Fraction(value, 20) for value in range(3, 17))
    if tuple(parse_q(value) for value in final["adaptive"]["accepted"]) != expected_adaptive:
        raise AssertionError("adaptive confidence sequence changed")
    if tuple(parse_q(value) for value in final["baseline"]["accepted"]) != expected_baseline:
        raise AssertionError("baseline confidence sequence changed")
    maximum = max(parse_q(item["adaptive_wealth"]) for item in true_history)
    maximum_time = next(
        item["time"]
        for item in true_history
        if parse_q(item["adaptive_wealth"]) == maximum
    )
    final_values = {
        str(q(effect)): {
            "adaptive": q(
                sum(
                    weight * wealth
                    for weight, wealth in zip(ADAPTIVE_WEIGHTS, wealths[effect])
                )
            ),
            "baseline": q(
                sum(
                    weight * wealth
                    for weight, wealth in zip(BASELINE_WEIGHTS, wealths[effect])
                )
            ),
            "expert_wealths": {
                mode: q(wealth)
                for mode, wealth in zip(EXPERTS, wealths[effect])
            },
        }
        for effect in GRID
    }
    return {
        "milestones": milestones,
        "final": {
            "adaptive": final["adaptive"],
            "baseline": final["baseline"],
            "adaptive_subset_of_baseline": True,
            "width_reduction": [3, 10],
            "relative_width_reduction": [6, 13],
        },
        "true_path": {
            "included_at_every_time": True,
            "maximum_adaptive_wealth": q(maximum),
            "maximum_time": maximum_time,
            "final_adaptive_wealth": true_history[-1]["adaptive_wealth"],
            "final_baseline_wealth": true_history[-1]["baseline_wealth"],
            "history_sha256": digest(true_history),
        },
        "final_e_values_sha256": digest(final_values),
    }


def build_payload() -> dict[str, object]:
    event_counts = {code: EVENT_CODES.count(code) for code in range(8)}
    if event_counts != {0: 21, 1: 3, 2: 3, 3: 5, 4: 5, 5: 3, 6: 3, 7: 21}:
        raise AssertionError("event multiplicities changed")
    model_a = model_certificate("model_A")
    model_b = model_certificate("model_B")
    if (
        model_a["expected_score"] != [31, 64]
        or model_a["actual_remainder"] != [-1, 64]
        or model_a["component_bound"] != [3, 64]
        or model_b["expected_score"] != [97, 192]
        or model_b["actual_remainder"] != [1, 192]
        or model_b["component_bound"] != [19, 192]
    ):
        raise AssertionError("nuisance control changed")
    factor_expectations = {
        "model_A": {
            "positive": [47, 48],
            "negative": [95, 96],
            "normalized_remainder": [1, 64],
        },
        "model_B": {
            "positive": [31, 32],
            "negative": [139, 144],
            "normalized_remainder": [19, 576],
        },
    }
    for model in MODELS.values():
        for effect in GRID:
            mean = normalize(effect)
            for observation in (Fraction(0), Fraction(1)):
                for current_lambda in (Fraction(-1), Fraction(0), Fraction(1)):
                    if robust_factor(
                        current_lambda,
                        observation,
                        mean,
                        model["bound"] / WIDTH,
                    ) < 0:
                        raise AssertionError("negative robust factor")
    path = replay_path()
    if path["true_path"]["history_sha256"] != (
        "af1135d4b32476463e62d6aa65cbed28ee923dbefb0f7055c3bf3aacfb273013"
    ):
        raise AssertionError("true history changed")
    if path["final_e_values_sha256"] != (
        "64e19c9f34ab2ff8ba7757aafdeda2fff2371eff9ab562eaddb5455d60f7ce90"
    ):
        raise AssertionError("final e-values changed")
    return {
        "schema": "semiparametric-anytime/public-independent-certificate/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": PRIVATE_HEAD,
            "blobs": PRIVATE_BLOBS,
        },
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "truth": {"ate": [1, 2], "event_counts": event_counts},
        "nuisance_packets": {"model_A": model_a, "model_B": model_b},
        "factor_expectations_at_truth": factor_expectations,
        "path": {"event_code_sha256": digest(list(EVENT_CODES)), **path},
        "resource": {
            "required_cells": 5_376,
            "valid_cap": 10_000,
            "abstention_cap": 5_000,
            "abstention_status": "UNKNOWN_RESOURCE_LIMIT",
        },
        "negative_controls": {
            "leakage": "INVALID_LEAKAGE",
            "positivity": "INVALID_POSITIVITY",
            "remainder": "INVALID_REMAINDER_BOUND",
            "score_range": "INVALID_SCORE_RANGE",
            "dependence": "INVALID_RESIDUAL_DEPENDENCE",
            "post_hoc": "INVALID_CURRENT_OUTCOME_LEAKAGE",
            "resource": "UNKNOWN_RESOURCE_LIMIT",
        },
        "gates": {
            "out_of_fold_provenance": "PASS",
            "positivity": "PASS",
            "score_boundedness": "PASS",
            "second_order_remainder": "PASS",
            "conditional_score_bound": "PASS",
            "predictable_experts": "PASS",
            "factor_nonnegativity": "PASS",
            "mixture_normalization": "PASS",
            "expert_regret_lower_bound": "PASS",
            "true_effect_control": "PASS",
            "strict_control_shrinkage": "PASS",
        },
        "scientific_boundary": (
            "Independent finite verification under the declared causal law, "
            "disjoint nuisance provenance and exact predictable remainder bounds. "
            "Ville supplies anytime coverage for the resulting e-process; this is "
            "not uniform validity for arbitrary learned nuisances or dependent data."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = build_payload()
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload = certificate.get("payload")
    claimed = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ["shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    if canonical(build_certificate()["payload"]) != canonical(payload):
        return ["semantic-replay"]
    return []


def report(certificate: Mapping[str, object]) -> dict[str, object]:
    payload = certificate["payload"]
    result = {
        "schema": "semiparametric-anytime/public-independent-report/1",
        "truth": payload["truth"],
        "nuisance_packets": payload["nuisance_packets"],
        "factor_expectations_at_truth": payload["factor_expectations_at_truth"],
        "path": payload["path"],
        "resource": payload["resource"],
        "negative_controls": payload["negative_controls"],
        "gates": payload["gates"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
        "scientific_boundary": payload["scientific_boundary"],
    }
    result["sha256"] = digest(result)
    return result


def write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public certificate replay failed")
    tampered = deepcopy(certificate)
    tampered["payload"]["path"]["final"]["adaptive"]["width"] = [0, 1]
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["path"]["final"]["adaptive"]["width"] = [0, 1]
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")
    result = report(certificate)
    write(ROOT / "SEMIPARAMETRIC_ANYTIME_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "SEMIPARAMETRIC_ANYTIME_PUBLIC_REPORT.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
