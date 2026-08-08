from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path

from logic_power_v10.certificate import canonical_json

from finite_sample_design import (
    build_finite_sample_certificate,
    causal_sampling_problem,
    verify_finite_sample_certificate,
)

ROOT = Path(__file__).resolve().parent


def _assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(
            f"{label}: expected {expected!r}, got {actual!r}"
        )


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    observational = build_finite_sample_certificate(
        causal_sampling_problem(observational_only=True),
        "finite_sample_observational_noninformation",
    )
    interventional = build_finite_sample_certificate(
        causal_sampling_problem(),
        "finite_sample_interventional_minimax_design",
    )

    for name, certificate in (
        ("observational", observational),
        ("interventional", interventional),
    ):
        errors = verify_finite_sample_certificate(certificate)
        if errors:
            raise AssertionError(f"{name} replay failed: {errors}")

    observational_solution = observational["payload"]["solution"]
    interventional_solution = interventional["payload"]["solution"]

    _assert_equal(
        observational_solution["value"],
        [1, 2],
        "observation-only minimax value",
    )
    _assert_equal(
        observational_solution["least_favorable_prior"],
        {
            "confounded_no_effect": [1, 2],
            "direct_positive_effect": [1, 2],
        },
        "observation-only least favorable prior",
    )

    _assert_equal(
        interventional_solution["value"],
        [13, 49],
        "interventional minimax value",
    )
    _assert_equal(
        interventional_solution["frontier_sizes_by_horizon"],
        [2, 4, 7],
        "policy frontier sizes",
    )
    _assert_equal(
        interventional_solution["policy_count"],
        7,
        "final deterministic policy count",
    )
    _assert_equal(
        interventional_solution["least_favorable_prior"],
        {
            "confounded_no_effect": [36, 49],
            "direct_positive_effect": [13, 49],
        },
        "least favorable causal prior",
    )
    support = interventional_solution["randomized_policy_support"]
    _assert_equal(
        [item["weight"] for item in support],
        [[9, 49], [40, 49]],
        "minimax policy mixture weights",
    )
    _assert_equal(
        [item["risks"] for item in support],
        [[[0, 1], [1, 1]], [[13, 40], [1, 10]]],
        "support risk vectors",
    )
    if any(
        "observe_proxy" in canonical_json(item["tree"])
        for item in support
    ):
        raise AssertionError(
            "no-information observational sampling entered minimax support"
        )

    tampered = copy.deepcopy(interventional)
    tampered["payload"]["solution"]["value"] = [1, 4]
    _assert_equal(
        verify_finite_sample_certificate(tampered),
        ["payload-hash"],
        "tampered finite-sample certificate rejection",
    )

    report = {
        "schema": (
            "inference-power-compiler/"
            "finite-sample-minimax-design-report/1"
        ),
        "scope": (
            "two finite causal worlds, binary actions, exact rational "
            "sampling kernels and costs, horizon two, randomized mixtures "
            "over deterministic adaptive policies"
        ),
        "observation_only": {
            "minimax_value": observational_solution["value"],
            "least_favorable_prior": observational_solution[
                "least_favorable_prior"
            ],
            "interpretation": (
                "The observational kernel is identical in both worlds. "
                "The exact minimax compiler assigns it no support and the "
                "value remains one half."
            ),
        },
        "interventional_design": {
            "minimax_value": interventional_solution["value"],
            "frontier_sizes_by_horizon": interventional_solution[
                "frontier_sizes_by_horizon"
            ],
            "deterministic_policy_count": interventional_solution[
                "policy_count"
            ],
            "least_favorable_prior": interventional_solution[
                "least_favorable_prior"
            ],
            "randomized_support": support,
            "world_risks": interventional_solution["world_risks"],
            "primal_vertices_examined": interventional_solution[
                "primal_vertices_examined"
            ],
            "dual_vertices_examined": interventional_solution[
                "dual_vertices_examined"
            ],
            "theorem": (
                "The exact minimax value is 13/49. With probability 9/49 "
                "the rule stops and declares no effect; with probability "
                "40/49 it samples the intervention up to twice, stopping "
                "no-effect after any zero and declaring positive effect "
                "after two ones."
            ),
        },
        "independent_wolfram": {
            "primal_value": [13, 49],
            "dual_value": [13, 49],
            "positive_support_indices_one_based": [1, 4],
            "positive_support_weights": [[9, 49], [40, 49]],
            "least_favorable_no_effect_weight": [36, 49],
            "zero_gap": True,
        },
        "certificates": {
            "observational_sha256": observational["sha256"],
            "interventional_sha256": interventional["sha256"],
            "semantic_replay": "PASS",
            "tampered_certificate": "REJECTED:payload-hash",
        },
    }
    report["sha256"] = sha256(
        canonical_json(report).encode("utf-8")
    ).hexdigest()

    _write(
        ROOT / "FINITE_SAMPLE_OBSERVATIONAL_CERTIFICATE.json",
        observational,
    )
    _write(
        ROOT / "FINITE_SAMPLE_INTERVENTIONAL_CERTIFICATE.json",
        interventional,
    )
    _write(ROOT / "FINITE_SAMPLE_MINIMAX_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
