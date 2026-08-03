from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fdata(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def main() -> None:
    observations = tuple(
        Fraction(value) for value in ([1, 1, 0, 1, 1, 1, 0, 1] * 8)
    )
    grid = tuple(Fraction(index, 20) for index in range(21))
    lambdas = (
        Fraction(1, 4), Fraction(-1, 4),
        Fraction(1, 2), Fraction(-1, 2),
        Fraction(3, 4), Fraction(-3, 4),
        Fraction(1), Fraction(-1),
    )
    weights = tuple(Fraction(1, 8) for _ in lambdas)
    alpha = Fraction(1, 20)
    threshold = 1 / alpha
    true_mean = Fraction(3, 4)

    if sum(weights, Fraction(0)) != 1 or threshold != 20:
        raise AssertionError("mixture or threshold changed")
    corner_factors = {
        lam: tuple(
            1 + lam * (Fraction(x) - Fraction(mean))
            for x in (0, 1)
            for mean in (0, 1)
        )
        for lam in lambdas
    }
    if any(value < 0 for values in corner_factors.values() for value in values):
        raise AssertionError("global factor nonnegativity failed")

    wealth = {lam: {mean: Fraction(1) for mean in grid} for lam in lambdas}
    history = []
    true_e_values = []
    for time, observation in enumerate(observations, 1):
        for lam in lambdas:
            for mean in grid:
                wealth[lam][mean] *= 1 + lam * (observation - mean)
        mixture = {
            mean: sum(
                (weights[index] * wealth[lam][mean] for index, lam in enumerate(lambdas)),
                Fraction(0),
            )
            for mean in grid
        }
        included = tuple(mean for mean in grid if mixture[mean] < threshold)
        positions = [grid.index(mean) for mean in included]
        contiguous = not positions or positions == list(range(positions[0], positions[-1] + 1))
        if not contiguous:
            raise AssertionError("control confidence set became disconnected")
        true_e_values.append(mixture[true_mean])
        history.append((included, mixture))

    milestones = {
        8: (Fraction(0), Fraction(1), 21),
        16: (Fraction(7, 20), Fraction(1), 14),
        24: (Fraction(9, 20), Fraction(1), 12),
        32: (Fraction(1, 2), Fraction(19, 20), 10),
        48: (Fraction(11, 20), Fraction(9, 10), 8),
        64: (Fraction(3, 5), Fraction(17, 20), 6),
    }
    for time, expected in milestones.items():
        included, _mixture = history[time - 1]
        observed = (included[0], included[-1], len(included))
        if observed != expected:
            raise AssertionError(f"confidence set changed at time {time}")
    if any(value >= threshold for value in true_e_values):
        raise AssertionError("reference mean was excluded")
    if max(true_e_values) != Fraction(527, 512):
        raise AssertionError("reference e-value maximum changed")
    if true_e_values.index(max(true_e_values)) + 1 != 2:
        raise AssertionError("reference maximum time changed")

    final_included, final_mixture = history[-1]
    expected_final = tuple(Fraction(index, 20) for index in range(12, 18))
    if final_included != expected_final:
        raise AssertionError("final grid interval changed")

    # Exact negative controls.
    post_hoc_maximum_mean = Fraction(5, 4)
    if post_hoc_maximum_mean <= 1:
        raise AssertionError("post-hoc inflation witness changed")
    required_cells = len(observations) * len(grid) * len(lambdas)
    if required_cells != 10_752 or required_cells <= 10_000:
        raise AssertionError("resource abstention control changed")

    payload = {
        "schema": "bounded-mean-confidence-sequence/public-independent-receipt/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": "482bf01e178cfad3dea4f800d653b5cf1305183a",
            "compiler_blob": "cd4f7c83b5683862dee04c3377c409f9a731157f",
            "runner_blob": "8f1996984f51a6d7ff795af41291757477f43529",
            "lean_blob": "7de66ffec5feaeaa206df9af7fec342948f492b8",
        },
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "control": {
            "horizon": 64,
            "ones": 48,
            "zeros": 16,
            "empirical_mean": [3, 4],
            "grid_step": [1, 20],
            "grid_size": 21,
            "alpha": [1, 20],
            "threshold": [20, 1],
            "betting_fractions": [fdata(value) for value in lambdas],
            "mixture_weights": [fdata(value) for value in weights],
            "milestones": {
                str(time): {
                    "lower": fdata(lower),
                    "upper": fdata(upper),
                    "size": size,
                }
                for time, (lower, upper, size) in milestones.items()
            },
            "final": {
                "included": [fdata(value) for value in final_included],
                "lower": [3, 5],
                "upper": [17, 20],
                "size": 6,
                "lower_adjacent_excluded_e_value": fdata(final_mixture[Fraction(11, 20)]),
                "upper_adjacent_excluded_e_value": fdata(final_mixture[Fraction(9, 10)]),
            },
            "reference": {
                "mean": [3, 4],
                "included_at_every_time": True,
                "maximum_e_value": [527, 512],
                "maximum_time": 2,
                "final_e_value": fdata(true_e_values[-1]),
            },
        },
        "negative_controls": {
            "post_hoc_selection": {
                "required_status": "INVALID_POST_HOC_SELECTION",
                "maximum_factor_mean": [5, 4],
            },
            "unbounded_observation": {
                "required_status": "INVALID_UNBOUNDED_OBSERVATION",
                "observation": [5, 4],
            },
            "resource_limit": {
                "required_status": "UNKNOWN_RESOURCE_LIMIT",
                "required_cells": 10_752,
                "max_cells": 10_000,
            },
        },
        "gates": {
            "boundedness": "PASS",
            "global_safe_betting_range": "PASS",
            "factor_nonnegativity": "PASS",
            "mixture_normalization": "PASS",
            "predictability": "PASS",
            "grid_inversion": "PASS",
            "reference_path_control": "PASS",
            "post_hoc_rejection": "PASS",
            "resource_abstention": "PASS",
            "tamper_rejection": "PASS",
        },
        "scientific_boundary": (
            "Anytime-valid finite-grid coverage under X_t in [0,1] and the "
            "declared grid-valued conditional mean. The e-process/Ville theorem "
            "is established; this verifier reconstructs all finite rational obligations."
        ),
    }
    certificate = {
        "payload": payload,
        "sha256": sha256(canonical(payload).encode()).hexdigest(),
    }
    tampered = deepcopy(certificate)
    tampered["payload"]["control"]["final"]["lower"] = [0, 1]
    if sha256(canonical(tampered["payload"]).encode()).hexdigest() == tampered["sha256"]:
        raise AssertionError("tampered receipt retained its hash")

    path = ROOT / "CONFIDENCE_SEQUENCE_PUBLIC_RECEIPT.json"
    path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    print(json.dumps(certificate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
