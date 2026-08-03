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
        "systems_optimizer_only",
        "broad_ml_model_analyst",
        "broad_data_science_capability",
    )
    property_values = {
        "systems_optimizer_only": False,
        "broad_ml_model_analyst": True,
        "broad_data_science_capability": True,
    }
    experiments = (
        experiment(
            "more_tool_routing_seeds",
            1,
            {hypothesis: "PASS" for hypothesis in hypotheses},
        ),
        experiment(
            "retune_seen_safety_private_split",
            1,
            {hypothesis: "POST_HOC_INVALID" for hypothesis in hypotheses},
        ),
        experiment(
            "resnet_bit_flip_transfer",
            3,
            {
                "systems_optimizer_only": "FAIL",
                "broad_ml_model_analyst": "PASS",
                "broad_data_science_capability": "PASS",
            },
        ),
        experiment(
            "multilingual_ocr_l40s",
            30,
            {
                "systems_optimizer_only": "FAIL",
                "broad_ml_model_analyst": "PASS",
                "broad_data_science_capability": "PASS",
            },
        ),
        experiment(
            "scaling_law_h100",
            40,
            {
                "systems_optimizer_only": "FAIL",
                "broad_ml_model_analyst": "PASS",
                "broad_data_science_capability": "PASS",
            },
        ),
    )
    prior = {
        "systems_optimizer_only": Fraction(1, 2),
        "broad_ml_model_analyst": Fraction(1, 4),
        "broad_data_science_capability": Fraction(1, 4),
    }
    problem = ActiveDiscoveryProblem(
        hypotheses, property_values, experiments, prior
    )
    certificate = build_certificate(
        problem, "next-gate-after-agent-tool-routing-hidden-pass"
    )
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")
    analysis = certificate["payload"]["analysis"]
    policy = analysis["policy"]
    basis = analysis["fixed_basis"]
    if not policy["exact"]:
        raise SystemExit("original Logic Power v10 found no exact experiment")
    if policy["tree"]["experiment"] != "resnet_bit_flip_transfer":
        raise SystemExit(f"unexpected first experiment: {policy['tree']}")
    if basis != ["resnet_bit_flip_transfer"]:
        raise SystemExit(f"unexpected fixed basis: {basis}")

    receipt = {
        "schema": "data-science-god-level/resnet-bitflip-logic-plan/1",
        "logic_power_v10_private_head": (
            "ba10d0edc7eb20d499d0481fda2537e782b6efb2"
        ),
        "problem_solver_role": (
            "minimum free portfolio under cost, validity, and information gain"
        ),
        "prior_evidence": {
            "adaptive_compression": {
                "verdict": "PASS",
                "run": 30828345539,
                "candidate_bpb": 3.5266205224273532,
                "reference_bpb": 3.8,
            },
            "safety_router": {
                "verdict": "FAIL",
                "private_run": 30830777293,
                "private_accuracy": 0.6359375,
                "required_accuracy": 0.64,
            },
            "agent_tool_routing": {
                "verdict": "PASS",
                "hidden_run": 30859222616,
                "metric_seconds": 0.159752,
                "reference_seconds": 0.40,
                "mrr": 0.985403,
                "recall": 1.0,
            },
        },
        "selected_experiment": "resnet_bit_flip_transfer",
        "selection_reason": (
            "lowest-cost external CPU gate that separates systems optimization "
            "from adaptive model analysis; GPU alternatives are dominated"
        ),
        "rejected_experiments": {
            "more_tool_routing_seeds": "no separating power",
            "retune_seen_safety_private_split": "post-hoc and inadmissible",
            "multilingual_ocr_l40s": "separating but requires paid L40S",
            "scaling_law_h100": "separating but requires paid H100",
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
