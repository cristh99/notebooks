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
        "easy_suite_only_predictor",
        "medium_physics_predictor",
        "external_variable_selector",
        "broad_scientific_equation_discoverer",
    )
    property_map = {
        "closed_grammar_synthetic_specialist": False,
        "easy_suite_only_predictor": False,
        "medium_physics_predictor": True,
        "external_variable_selector": True,
        "broad_scientific_equation_discoverer": True,
    }
    experiments = (
        _experiment(
            "all_40_srsd_medium_dummy_cpu",
            14,
            {
                "closed_grammar_synthetic_specialist": "FAIL",
                "easy_suite_only_predictor": "FAIL",
                "medium_physics_predictor": "PASS",
                "external_variable_selector": "PASS",
                "broad_scientific_equation_discoverer": "PASS",
            },
        ),
        _experiment(
            "medium_grammar_compatible_subset",
            6,
            {hypothesis: "PASS" for hypothesis in hypotheses},
        ),
        _experiment(
            "gpu_sota_medium_comparison",
            55,
            {
                "closed_grammar_synthetic_specialist": "FAIL",
                "easy_suite_only_predictor": "FAIL",
                "medium_physics_predictor": "PASS",
                "external_variable_selector": "PASS",
                "broad_scientific_equation_discoverer": "PASS",
            },
        ),
        _experiment(
            "retune_after_medium_truth",
            1,
            {hypothesis: "POST_HOC_INVALID" for hypothesis in hypotheses},
        ),
    )
    problem = ActiveDiscoveryProblem(
        hypotheses,
        property_map,
        experiments,
        {hypothesis: Fraction(1, 5) for hypothesis in hypotheses},
    )
    certificate = build_certificate(problem, "fresh-medium-gate-after-easy-suite-invalid-run")
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")
    selected = "all_40_srsd_medium_dummy_cpu"
    analysis = certificate["payload"]["analysis"]
    if not analysis["policy"]["exact"]:
        raise SystemExit("no exact separating policy")
    if analysis["policy"]["tree"]["experiment"] != selected:
        raise SystemExit(f"unexpected experiment: {analysis['policy']['tree']}")
    if analysis["fixed_basis"] != [selected]:
        raise SystemExit(f"unexpected basis: {analysis['fixed_basis']}")

    receipt = {
        "schema": "data-science-god-level/symbolic-discovery-srsd-medium-plan/1",
        "logic_power_v10_private_head": "ba10d0edc7eb20d499d0481fda2537e782b6efb2",
        "selected_experiment": selected,
        "selection_reason": "the untouched complete 40-task medium suite is the least-cost admissible experiment after the easy suite became protocol-exposed without producing metrics",
        "rejected_experiments": {
            "medium_grammar_compatible_subset": "post-selection compatibity filtering would not separate a closed grammar specialist",
            "gpu_sota_medium_comparison": "separating but dominated by paid compute before CPU transfer is established",
            "retune_after_medium_truth": "post-hoc and inadmissible",
        },
        "candidate_frozen_before_medium_data_access": True,
        "dataset_selection_rule": "all 40 SRSD-Feynman Medium Dummy equations",
        "easy_suite_status": "RETIRED_AFTER_INVALID_INCOMPLETE_RUN_WITHOUT_METRICS",
        "certificate": certificate,
    }
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    Path("srsd-medium-plan-receipt.json").write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
