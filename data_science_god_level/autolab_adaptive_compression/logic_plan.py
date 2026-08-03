from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from logic_power_v10.active_discovery import ActiveDiscoveryProblem, Experiment
from logic_power_v10.certificate import build_certificate, verify_certificate


def exp(name: str, cost: int, observations: dict[str, str]) -> Experiment:
    return Experiment(name=name, cost=Fraction(cost), observations=observations)


def main() -> None:
    hypotheses = (
        "numpy_version_artifact",
        "evaluator_hack",
        "portable_external_win",
    )
    property_values = {
        "numpy_version_artifact": False,
        "evaluator_hack": False,
        "portable_external_win": True,
    }
    experiments = (
        exp(
            "more_internal_tests",
            1,
            {hypothesis: "PASS" for hypothesis in hypotheses},
        ),
        exp(
            "clean_numpy126_replay",
            2,
            {
                "numpy_version_artifact": "FAIL",
                "evaluator_hack": "PASS",
                "portable_external_win": "PASS",
            },
        ),
        exp(
            "evaluator_integrity_redteam",
            4,
            {
                "numpy_version_artifact": "PASS",
                "evaluator_hack": "FAIL",
                "portable_external_win": "PASS",
            },
        ),
    )
    prior = {
        "numpy_version_artifact": Fraction(4, 8),
        "evaluator_hack": Fraction(1, 8),
        "portable_external_win": Fraction(3, 8),
    }
    problem = ActiveDiscoveryProblem(
        hypotheses,
        property_values,
        experiments,
        prior,
    )
    certificate = build_certificate(problem, "portable-external-win")
    if verify_certificate(certificate):
        raise SystemExit("Logic Power v10 certificate replay failed")
    policy = certificate["payload"]["analysis"]["policy"]
    if not policy["exact"]:
        raise SystemExit("Logic Power v10 did not synthesize an exact policy")
    if policy["tree"]["experiment"] != "clean_numpy126_replay":
        raise SystemExit("unexpected first experiment")
    basis = certificate["payload"]["analysis"]["fixed_basis"]
    if basis != ["clean_numpy126_replay", "evaluator_integrity_redteam"]:
        raise SystemExit(f"unexpected fixed basis: {basis}")

    conditioned = ActiveDiscoveryProblem(
        ("evaluator_hack", "portable_external_win"),
        {
            "evaluator_hack": False,
            "portable_external_win": True,
        },
        (
            exp(
                "more_internal_tests",
                1,
                {
                    "evaluator_hack": "PASS",
                    "portable_external_win": "PASS",
                },
            ),
            exp(
                "evaluator_integrity_redteam",
                4,
                {
                    "evaluator_hack": "FAIL",
                    "portable_external_win": "PASS",
                },
            ),
        ),
        {
            "evaluator_hack": Fraction(1, 4),
            "portable_external_win": Fraction(3, 4),
        },
    )
    conditioned_certificate = build_certificate(
        conditioned,
        "portable-external-win-after-clean-pass",
    )
    if verify_certificate(conditioned_certificate):
        raise SystemExit("conditioned certificate replay failed")
    next_experiment = conditioned_certificate["payload"]["analysis"]["policy"]["tree"]["experiment"]
    if next_experiment != "evaluator_integrity_redteam":
        raise SystemExit("unexpected conditioned experiment")

    receipt = {
        "schema": "data-science-god-level/logic-power-v10-plan/1",
        "logic_power_v10_private_head": "ba10d0edc7eb20d499d0481fda2537e782b6efb2",
        "first_experiment": "clean_numpy126_replay",
        "second_experiment_after_pass": "evaluator_integrity_redteam",
        "fixed_basis": basis,
        "certificate": certificate,
        "conditioned_certificate": conditioned_certificate,
    }
    Path("logic-plan-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
