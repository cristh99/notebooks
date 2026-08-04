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
        "prior_benchmark_specialist",
        "systems_and_supervised_only",
        "generic_unsupervised_anomaly_scientist",
        "broad_data_science_capability",
    )
    property_map = {
        "prior_benchmark_specialist": False,
        "systems_and_supervised_only": False,
        "generic_unsupervised_anomaly_scientist": True,
        "broad_data_science_capability": True,
    }
    experiments = (
        _experiment(
            "repeat_supervised_tabular_transfer",
            1,
            {hypothesis: "PASS" for hypothesis in hypotheses},
        ),
        _experiment(
            "retune_seen_twins_truth",
            1,
            {hypothesis: "POST_HOC_INVALID" for hypothesis in hypotheses},
        ),
        _experiment(
            "cpu_unsupervised_multigeometry_anomaly_transfer",
            4,
            {
                "prior_benchmark_specialist": "FAIL",
                "systems_and_supervised_only": "FAIL",
                "generic_unsupervised_anomaly_scientist": "PASS",
                "broad_data_science_capability": "PASS",
            },
        ),
        _experiment(
            "h100_diffusion_anomaly_foundation_model",
            40,
            {
                "prior_benchmark_specialist": "FAIL",
                "systems_and_supervised_only": "FAIL",
                "generic_unsupervised_anomaly_scientist": "PASS",
                "broad_data_science_capability": "PASS",
            },
        ),
        _experiment(
            "prospective_production_anomaly_intervention",
            100,
            {
                "prior_benchmark_specialist": "FAIL",
                "systems_and_supervised_only": "FAIL",
                "generic_unsupervised_anomaly_scientist": "PASS",
                "broad_data_science_capability": "PASS",
            },
        ),
    )
    priors = {hypothesis: Fraction(1, 4) for hypothesis in hypotheses}
    problem = ActiveDiscoveryProblem(hypotheses, property_map, experiments, priors)
    certificate = build_certificate(
        problem,
        "next-gate-after-tabular-transfer-pass",
    )
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")
    analysis = certificate["payload"]["analysis"]
    selected = "cpu_unsupervised_multigeometry_anomaly_transfer"
    if not analysis["policy"]["exact"]:
        raise SystemExit("no exact separating policy")
    if analysis["policy"]["tree"]["experiment"] != selected:
        raise SystemExit(f"unexpected experiment: {analysis['policy']['tree']}")
    if analysis["fixed_basis"] != [selected]:
        raise SystemExit(f"unexpected basis: {analysis['fixed_basis']}")
    receipt = {
        "schema": "data-science-god-level/unsupervised-anomaly-logic-plan/1",
        "logic_power_v10_private_head": "ba10d0edc7eb20d499d0481fda2537e782b6efb2",
        "problem_solver_role": "minimum admissible independent portfolio under validity, information gain, cost, and zero paid compute",
        "consensus_evidence": {
            "adbench": "30 algorithms on 57 datasets; algorithm selection is consequential",
            "bouman_2023": "kNN is strongest on local anomalies and EIF on global anomalies",
            "deep_isolation_forest": "random representations reduce axis-parallel isolation bias",
        },
        "prior_evidence": {
            "tabular_supervised_transfer": "OFFICIAL_PASS_6_OF_6",
            "realcause_twins": "OFFICIAL_FAIL_ABSOLUTE_PEHE",
            "resnet_bit_flip": "OFFICIAL_PASS",
        },
        "selected_experiment": selected,
        "selection_reason": "lowest-cost fresh external gate separating label-free anomaly discovery from systems-only, supervised-only, or prior-benchmark specialization",
        "rejected_experiments": {
            "repeat_supervised_tabular_transfer": "non-separating repetition",
            "retune_seen_twins_truth": "post-hoc and inadmissible",
            "h100_diffusion_anomaly_foundation_model": "separating but dominated by paid GPU cost",
            "prospective_production_anomaly_intervention": "stronger external validity but unavailable and dominated now",
        },
        "public_roles": ["p01", "p02", "p03", "p04", "p05", "p06"],
        "official_roles": ["o01", "o02", "o03", "o04", "o05", "o06"],
        "candidate_label_access": False,
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
