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
        "broad_data_science_with_cate_weakness",
        "generic_supervised_modeler",
        "systems_and_aggregate_effects_only",
        "prior_benchmark_specialist",
    )
    problem = ActiveDiscoveryProblem(
        hypotheses,
        {
            "broad_data_science_with_cate_weakness": True,
            "generic_supervised_modeler": True,
            "systems_and_aggregate_effects_only": False,
            "prior_benchmark_specialist": False,
        },
        (
            _experiment(
                "repeat_systems_benchmarks",
                1,
                {hypothesis: "PASS" for hypothesis in hypotheses},
            ),
            _experiment(
                "retune_seen_twins_truth",
                1,
                {hypothesis: "POST_HOC_INVALID" for hypothesis in hypotheses},
            ),
            _experiment(
                "cpu_multidataset_tabular_transfer",
                3,
                {
                    "broad_data_science_with_cate_weakness": "PASS",
                    "generic_supervised_modeler": "PASS",
                    "systems_and_aggregate_effects_only": "FAIL",
                    "prior_benchmark_specialist": "FAIL",
                },
            ),
            _experiment(
                "cpu_unsupervised_anomaly_transfer",
                6,
                {
                    "broad_data_science_with_cate_weakness": "PASS",
                    "generic_supervised_modeler": "UNKNOWN",
                    "systems_and_aggregate_effects_only": "FAIL",
                    "prior_benchmark_specialist": "FAIL",
                },
            ),
            _experiment(
                "cpu_time_series_transfer",
                7,
                {
                    "broad_data_science_with_cate_weakness": "PASS",
                    "generic_supervised_modeler": "PASS",
                    "systems_and_aggregate_effects_only": "FAIL",
                    "prior_benchmark_specialist": "FAIL",
                },
            ),
            _experiment(
                "h100_world_model",
                40,
                {
                    "broad_data_science_with_cate_weakness": "PASS",
                    "generic_supervised_modeler": "FAIL",
                    "systems_and_aggregate_effects_only": "FAIL",
                    "prior_benchmark_specialist": "FAIL",
                },
            ),
        ),
        {
            "broad_data_science_with_cate_weakness": Fraction(1, 4),
            "generic_supervised_modeler": Fraction(1, 4),
            "systems_and_aggregate_effects_only": Fraction(1, 4),
            "prior_benchmark_specialist": Fraction(1, 4),
        },
    )
    certificate = build_certificate(
        problem, "next-gate-after-realcause-twins-hidden-fail"
    )
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"Logic Power v10 replay failed: {errors}")
    analysis = certificate["payload"]["analysis"]
    if not analysis["policy"]["exact"]:
        raise SystemExit("no exact separating policy")
    first = analysis["policy"]["tree"]["experiment"]
    if first != "cpu_multidataset_tabular_transfer":
        raise SystemExit(f"unexpected experiment: {analysis['policy']['tree']}")
    if analysis["fixed_basis"] != ["cpu_multidataset_tabular_transfer"]:
        raise SystemExit(f"unexpected basis: {analysis['fixed_basis']}")

    receipt = {
        "schema": "data-science-god-level/tabular-transfer-logic-plan/1",
        "logic_power_v10_private_head": "ba10d0edc7eb20d499d0481fda2537e782b6efb2",
        "problem_solver_role": (
            "minimum admissible independent portfolio under cost, validity, "
            "information gain, and no paid compute"
        ),
        "prior_evidence": {
            "adaptive_compression": "PASS",
            "agent_tool_routing": "PASS",
            "resnet_bit_flip": "PASS",
            "safety_router": "FAIL",
            "realcause_twins": "FAIL_ABSOLUTE_PEHE",
        },
        "selected_experiment": "cpu_multidataset_tabular_transfer",
        "selection_reason": (
            "lowest-cost fresh CPU gate separating generic supervised transfer "
            "from systems-only or prior-benchmark specialization"
        ),
        "rejected_experiments": {
            "repeat_systems_benchmarks": "no separating power",
            "retune_seen_twins_truth": "post-hoc and inadmissible",
            "cpu_unsupervised_anomaly_transfer": (
                "valuable next gate but dominated until supervised transfer is established"
            ),
            "cpu_time_series_transfer": "separating but higher cost",
            "h100_world_model": "separating but paid H100 is dominated",
        },
        "public_suite": {
            "classification": [
                "credit_approval_australia",
                "phoneme",
                "spambase",
            ],
            "regression": ["197_cpu_act", "503_wind", "529_pollen"],
        },
        "official_suite": {
            "classification": [
                "breast_cancer_wisconsin_diagnostic",
                "hill_valley_with_noise",
                "magic",
            ],
            "regression": ["537_houses", "505_tecator", "522_pm10"],
        },
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
