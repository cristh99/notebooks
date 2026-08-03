from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from logic_power_v10.active_discovery import ActiveDiscoveryProblem, Experiment
from logic_power_v10.certificate import build_certificate, verify_certificate


def experiment(
    name: str,
    cost: int,
    observations: dict[str, str],
) -> Experiment:
    return Experiment(
        name=name,
        cost=Fraction(cost),
        observations=observations,
    )


def main() -> None:
    hypotheses = (
        "compression_specialist",
        "cross_domain_system_optimizer",
        "broad_but_safety_calibration_weak",
    )
    property_values = {
        "compression_specialist": False,
        "cross_domain_system_optimizer": True,
        "broad_but_safety_calibration_weak": True,
    }
    experiments = (
        experiment(
            "more_compression_seeds",
            1,
            {hypothesis: "PASS" for hypothesis in hypotheses},
        ),
        experiment(
            "retune_seen_safety_private_split",
            1,
            {hypothesis: "POST_HOC_INVALID" for hypothesis in hypotheses},
        ),
        experiment(
            "scaling_law_h100",
            30,
            {
                "compression_specialist": "FAIL",
                "cross_domain_system_optimizer": "PASS",
                "broad_but_safety_calibration_weak": "PASS",
            },
        ),
        experiment(
            "agent_tool_routing_hidden",
            2,
            {
                "compression_specialist": "FAIL",
                "cross_domain_system_optimizer": "PASS",
                "broad_but_safety_calibration_weak": "PASS",
            },
        ),
    )
    prior = {
        "compression_specialist": Fraction(1, 2),
        "cross_domain_system_optimizer": Fraction(1, 4),
        "broad_but_safety_calibration_weak": Fraction(1, 4),
    }
    problem = ActiveDiscoveryProblem(
        hypotheses,
        property_values,
        experiments,
        prior,
    )
    certificate = build_certificate(
        problem,
        "next-experiment-after-safety-router-private-fail",
    )
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")
    policy = certificate["payload"]["analysis"]["policy"]
    basis = certificate["payload"]["analysis"]["fixed_basis"]
    if not policy["exact"]:
        raise SystemExit("original Logic Power v10 found no exact experiment")
    if policy["tree"]["experiment"] != "agent_tool_routing_hidden":
        raise SystemExit(f"unexpected first experiment: {policy['tree']}")
    if basis != ["agent_tool_routing_hidden"]:
        raise SystemExit(f"unexpected fixed basis: {basis}")

    receipt = {
        "schema": "data-science-god-level/tool-routing-logic-plan/1",
        "logic_power_v10_private_head": (
            "ba10d0edc7eb20d499d0481fda2537e782b6efb2"
        ),
        "prior_evidence": {
            "adaptive_compression": {
                "run": 30828345539,
                "verdict": "PASS",
                "candidate_bpb": 3.5266205224273532,
                "reference_bpb": 3.8,
            },
            "safety_router": {
                "public_run": 30830318501,
                "private_run": 30830777293,
                "verdict": "FAIL",
                "private_accuracy": 0.6359375,
                "required_accuracy": 0.64,
            },
        },
        "selected_experiment": "agent_tool_routing_hidden",
        "rejected_experiments": {
            "more_compression_seeds": "no separating power",
            "retune_seen_safety_private_split": "post-hoc and no valid separating power",
            "scaling_law_h100": "separating but dominated by cost and unavailable free GPU",
        },
        "certificate": certificate,
    }
    Path("logic-plan-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
