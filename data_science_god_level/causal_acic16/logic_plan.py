from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from logic_power_v10.active_discovery import ActiveDiscoveryProblem, Experiment
from logic_power_v10.certificate import build_certificate, verify_certificate


def experiment(name: str, cost: int, observations: dict[str, str]) -> Experiment:
    return Experiment(name=name, cost=Fraction(cost), observations=observations)


def main() -> None:
    hypotheses = (
        "adaptive_neural_model_analyst",
        "internal_causal_compiler_only",
        "broad_data_science_capability",
    )
    property_values = {
        "adaptive_neural_model_analyst": False,
        "internal_causal_compiler_only": False,
        "broad_data_science_capability": True,
    }
    experiments = (
        experiment(
            "more_resnet_bitflip_seeds",
            1,
            {hypothesis: "PASS" for hypothesis in hypotheses},
        ),
        experiment(
            "self_generated_causal_replay",
            1,
            {
                "adaptive_neural_model_analyst": "FAIL",
                "internal_causal_compiler_only": "PASS",
                "broad_data_science_capability": "PASS",
            },
        ),
        experiment(
            "acic16_hidden_external",
            4,
            {
                "adaptive_neural_model_analyst": "FAIL",
                "internal_causal_compiler_only": "FAIL",
                "broad_data_science_capability": "PASS",
            },
        ),
        experiment(
            "acic2026_full_registered_challenge",
            20,
            {
                "adaptive_neural_model_analyst": "FAIL",
                "internal_causal_compiler_only": "FAIL",
                "broad_data_science_capability": "PASS",
            },
        ),
        experiment(
            "prospective_randomized_field_intervention",
            100,
            {
                "adaptive_neural_model_analyst": "FAIL",
                "internal_causal_compiler_only": "FAIL",
                "broad_data_science_capability": "PASS",
            },
        ),
    )
    prior = {
        "adaptive_neural_model_analyst": Fraction(1, 4),
        "internal_causal_compiler_only": Fraction(1, 2),
        "broad_data_science_capability": Fraction(1, 4),
    }
    problem = ActiveDiscoveryProblem(
        hypotheses, property_values, experiments, prior
    )
    certificate = build_certificate(
        problem, "next-gate-after-resnet-bitflip-official-pass"
    )
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")
    analysis = certificate["payload"]["analysis"]
    policy = analysis["policy"]
    basis = analysis["fixed_basis"]
    if not policy["exact"]:
        raise SystemExit("original Logic Power v10 found no exact experiment")
    if policy["tree"]["experiment"] != "acic16_hidden_external":
        raise SystemExit(f"unexpected first experiment: {policy['tree']}")
    if basis != ["acic16_hidden_external"]:
        raise SystemExit(f"unexpected fixed basis: {basis}")

    receipt = {
        "schema": "data-science-god-level/acic16-causal-logic-plan/1",
        "logic_power_v10_private_head": (
            "ba10d0edc7eb20d499d0481fda2537e782b6efb2"
        ),
        "problem_solver_role": (
            "minimum admissible external portfolio under cost, validity, "
            "independence, and information gain"
        ),
        "prior_evidence": {
            "adaptive_compression": {"verdict": "PASS"},
            "agent_tool_routing": {"verdict": "PASS"},
            "resnet_bit_flip": {
                "verdict": "PASS",
                "official_run": 30866105549,
                "accuracy": 0.0998,
                "bits_flipped": 40,
                "reference_bits": 40,
            },
            "internal_causal_compiler": {
                "verdict": "INTERNAL_ONLY",
                "absolute_external_credit": False,
            },
        },
        "selected_experiment": "acic16_hidden_external",
        "selection_reason": (
            "lowest-cost CPU gate that separates adaptive neural-model analysis "
            "and internal-only causal machinery from externally transferring "
            "causal/statistical data-science capability"
        ),
        "rejected_experiments": {
            "more_resnet_bitflip_seeds": "no separating power",
            "self_generated_causal_replay": (
                "cannot separate internal-only causal machinery from external transfer"
            ),
            "acic2026_full_registered_challenge": (
                "separating but registration, 9000 datasets, and higher cost are dominated"
            ),
            "prospective_randomized_field_intervention": (
                "stronger external validity but unavailable and dominated at this stage"
            ),
        },
        "public_instances": [1, 2, 3, 4, 5, 6],
        "official_instances": [7, 8, 9, 10],
        "official_truth_access_before_freeze": False,
        "certificate": certificate,
    }
    Path("logic-plan-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
