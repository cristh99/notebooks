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
        "synthetic_multiscale_specialist",
        "first_principles_only_symbolic_modeler",
        "real_blackbox_compact_modeler",
        "broad_symbolic_data_scientist",
    )
    property_map = {
        "synthetic_multiscale_specialist": False,
        "first_principles_only_symbolic_modeler": False,
        "real_blackbox_compact_modeler": True,
        "broad_symbolic_data_scientist": True,
    }
    experiments = (
        experiment(
            "repeat_internal_multiscale_suite",
            1,
            {hypothesis: "PASS" for hypothesis in hypotheses},
        ),
        experiment(
            "first_principles_only_gate",
            4,
            {
                "synthetic_multiscale_specialist": "FAIL",
                "first_principles_only_symbolic_modeler": "PASS",
                "real_blackbox_compact_modeler": "FAIL",
                "broad_symbolic_data_scientist": "PASS",
            },
        ),
        experiment(
            "all_24_srbench_2025_cpu",
            12,
            {
                "synthetic_multiscale_specialist": "FAIL",
                "first_principles_only_symbolic_modeler": "FAIL",
                "real_blackbox_compact_modeler": "PASS",
                "broad_symbolic_data_scientist": "PASS",
            },
        ),
        experiment(
            "full_25_method_srbench_container_campaign",
            100,
            {
                "synthetic_multiscale_specialist": "FAIL",
                "first_principles_only_symbolic_modeler": "FAIL",
                "real_blackbox_compact_modeler": "PASS",
                "broad_symbolic_data_scientist": "PASS",
            },
        ),
        experiment(
            "retune_after_srbench_truth",
            1,
            {hypothesis: "POST_HOC_INVALID" for hypothesis in hypotheses},
        ),
    )
    priors = {hypothesis: Fraction(1, 4) for hypothesis in hypotheses}
    problem = ActiveDiscoveryProblem(hypotheses, property_map, experiments, priors)
    certificate = build_certificate(problem, "symbolic-v2-next-gate-after-srsd-medium-fail")
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")
    analysis = certificate["payload"]["analysis"]
    selected = "all_24_srbench_2025_cpu"
    if not analysis["policy"]["exact"]:
        raise SystemExit("no exact separating policy")
    if analysis["policy"]["tree"]["experiment"] != selected:
        raise SystemExit(f"unexpected selected experiment: {analysis['policy']['tree']}")
    if analysis["fixed_basis"] != [selected]:
        raise SystemExit(f"unexpected fixed basis: {analysis['fixed_basis']}")
    receipt = {
        "schema": "data-science-god-level/symbolic-v2-srbench24-plan/1",
        "logic_power_v10_private_head": "ba10d0edc7eb20d499d0481fda2537e782b6efb2",
        "selected_experiment": selected,
        "selection_reason": "least-cost fresh external gate that jointly tests compact first-principles recovery and real black-box transfer across every official SRBench 2025 dataset definition",
        "rejected_experiments": {
            "repeat_internal_multiscale_suite": "non-separating repetition",
            "first_principles_only_gate": "cannot distinguish physics-only specialization from broad symbolic capability",
            "full_25_method_srbench_container_campaign": "separating but dominated by cost before the frozen candidate clears a one-shot CPU transfer gate",
            "retune_after_srbench_truth": "post-hoc and inadmissible",
        },
        "dataset_selection_rule": "all 12 black-box plus all 12 first-principles datasets in the pinned SRBench 2025 downloader",
        "candidate_frozen_before_dataset_values": True,
        "post_hoc_retuning_permitted": False,
        "certificate": certificate,
    }
    Path("srbench24-plan-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
