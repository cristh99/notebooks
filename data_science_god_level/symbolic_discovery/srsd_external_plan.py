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
        "closed_grammar_synthetic_specialist",
        "external_easy_physics_predictor",
        "external_variable_selector",
        "broad_scientific_equation_discoverer",
    )
    property_map = {
        "closed_grammar_synthetic_specialist": False,
        "external_easy_physics_predictor": True,
        "external_variable_selector": True,
        "broad_scientific_equation_discoverer": True,
    }
    experiments = (
        _experiment(
            "all_30_srsd_easy_dummy_cpu",
            10,
            {
                "closed_grammar_synthetic_specialist": "FAIL",
                "external_easy_physics_predictor": "PASS",
                "external_variable_selector": "PASS",
                "broad_scientific_equation_discoverer": "PASS",
            },
        ),
        _experiment(
            "grammar_compatible_srsd_subset",
            5,
            {hypothesis: "PASS" for hypothesis in hypotheses},
        ),
        _experiment(
            "gpu_sota_symbolic_methods_comparison",
            50,
            {
                "closed_grammar_synthetic_specialist": "FAIL",
                "external_easy_physics_predictor": "PASS",
                "external_variable_selector": "PASS",
                "broad_scientific_equation_discoverer": "PASS",
            },
        ),
        _experiment(
            "retune_after_srsd_truth",
            1,
            {hypothesis: "POST_HOC_INVALID" for hypothesis in hypotheses},
        ),
    )
    priors = {hypothesis: Fraction(1, 4) for hypothesis in hypotheses}
    problem = ActiveDiscoveryProblem(
        hypotheses,
        property_map,
        experiments,
        priors,
    )
    certificate = build_certificate(
        problem,
        "external-gate-after-prospective-symbolic-synthetic-pass",
    )
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")

    selected = "all_30_srsd_easy_dummy_cpu"
    analysis = certificate["payload"]["analysis"]
    if not analysis["policy"]["exact"]:
        raise SystemExit("no exact separating policy")
    if analysis["policy"]["tree"]["experiment"] != selected:
        raise SystemExit(f"unexpected experiment: {analysis['policy']['tree']}")
    if analysis["fixed_basis"] != [selected]:
        raise SystemExit(f"unexpected basis: {analysis['fixed_basis']}")

    receipt = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-external-plan/1",
        "logic_power_v10_private_head": "ba10d0edc7eb20d499d0481fda2537e782b6efb2",
        "selected_experiment": selected,
        "selection_reason": "the complete 30-task external suite is the least-cost admissible experiment that separates synthetic specialization from external transfer without cherry-picking",
        "rejected_experiments": {
            "grammar_compatible_srsd_subset": "non-separating because compatibility filtering can preserve a closed-grammar specialist",
            "gpu_sota_symbolic_methods_comparison": "separating but dominated by paid compute cost before the CPU transfer question is resolved",
            "retune_after_srsd_truth": "post-hoc and inadmissible",
        },
        "candidate_frozen_before_srsd_data_access": True,
        "dataset_selection_rule": "all 30 SRSD-Feynman Easy Dummy tasks",
        "consensus_evidence": {
            "srsd": "realistic variable ranges and dummy variables are designed to test scientific rediscovery and feature selection",
            "srbench": "accuracy, complexity and strong baselines should be evaluated jointly",
            "srbench_plus_plus": "feature selection and domain-relevant sub-tasks matter beyond expression size",
        },
        "certificate": certificate,
    }
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    Path("srsd-external-plan-receipt.json").write_text(
        payload,
        encoding="utf-8",
    )
    print(payload)


if __name__ == "__main__":
    main()
