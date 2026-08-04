from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from logic_power_v10.active_discovery import ActiveDiscoveryProblem, Experiment
from logic_power_v10.certificate import build_certificate, verify_certificate


def _experiment(name: str, cost: int, observations: dict[str, str]) -> Experiment:
    return Experiment(name=name, cost=Fraction(cost), observations=observations)


def main() -> None:
    hypotheses = (
        "acic_sample_specialist",
        "lalonde_family_causal_analyst",
        "cross_family_causal_data_scientist",
    )
    problem = ActiveDiscoveryProblem(
        hypotheses,
        {
            "acic_sample_specialist": False,
            "lalonde_family_causal_analyst": False,
            "cross_family_causal_data_scientist": True,
        },
        (
            _experiment(
                "rerun_exposed_acic16",
                1,
                {hypothesis: "POST_HOC_INVALID" for hypothesis in hypotheses},
            ),
            _experiment(
                "more_lalonde_samples",
                2,
                {hypothesis: "FAIL" if hypothesis == "acic_sample_specialist" else "PASS" for hypothesis in hypotheses},
            ),
            _experiment(
                "realcause_hidden_twins_transfer",
                5,
                {
                    "acic_sample_specialist": "FAIL",
                    "lalonde_family_causal_analyst": "FAIL",
                    "cross_family_causal_data_scientist": "PASS",
                },
            ),
            _experiment(
                "acic2026_registered_full_challenge",
                25,
                {
                    "acic_sample_specialist": "FAIL",
                    "lalonde_family_causal_analyst": "FAIL",
                    "cross_family_causal_data_scientist": "PASS",
                },
            ),
            _experiment(
                "prospective_field_intervention",
                100,
                {
                    "acic_sample_specialist": "FAIL",
                    "lalonde_family_causal_analyst": "FAIL",
                    "cross_family_causal_data_scientist": "PASS",
                },
            ),
        ),
        {
            "acic_sample_specialist": Fraction(1, 4),
            "lalonde_family_causal_analyst": Fraction(1, 2),
            "cross_family_causal_data_scientist": Fraction(1, 4),
        },
    )
    certificate = build_certificate(problem, "next-gate-after-acic16-protocol-invalid")
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")
    analysis = certificate["payload"]["analysis"]
    if not analysis["policy"]["exact"]:
        raise SystemExit("no exact separating policy")
    if analysis["policy"]["tree"]["experiment"] != "realcause_hidden_twins_transfer":
        raise SystemExit(f"unexpected experiment: {analysis['policy']['tree']}")
    if analysis["fixed_basis"] != ["realcause_hidden_twins_transfer"]:
        raise SystemExit(f"unexpected basis: {analysis['fixed_basis']}")

    receipt = {
        "schema": "data-science-god-level/realcause-logic-plan/1",
        "logic_power_v10_private_head": "ba10d0edc7eb20d499d0481fda2537e782b6efb2",
        "problem_solver_role": "minimum admissible independent portfolio under cost, validity and information gain",
        "prior_evidence": {
            "resnet_bit_flip": "PASS",
            "acic16": "STATISTICAL_PASS_PROTOCOL_INVALID_NO_CREDIT",
        },
        "selected_experiment": "realcause_hidden_twins_transfer",
        "selection_reason": "lowest-cost fresh external gate separating LaLonde-family competence from transfer to a distinct Twins causal family",
        "rejected_experiments": {
            "rerun_exposed_acic16": "post-hoc and inadmissible",
            "more_lalonde_samples": "cannot distinguish family specialization from broad transfer",
            "acic2026_registered_full_challenge": "separating but dominated by registration and scale cost",
            "prospective_field_intervention": "stronger external validity but unavailable and dominated now",
        },
        "public_families": ["lalonde_psid", "lalonde_cps"],
        "public_samples": [0, 1, 2, 3, 4, 5],
        "official_family": "twins",
        "official_samples": [90, 91, 92, 93, 94, 95, 96, 97, 98, 99],
        "official_truth_access_before_freeze": False,
        "certificate": certificate,
    }
    Path("logic-plan-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
