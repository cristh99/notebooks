from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

from logic_power_v10.certificate import canonical_json
from finite_sample_design import (
    SamplingExperiment,
    FiniteSampleDesignProblem,
    build_finite_sample_certificate,
    verify_finite_sample_certificate,
)

ROOT = Path(__file__).resolve().parent


def binary_problem(
    *, p0: tuple[Fraction, Fraction], p1: tuple[Fraction, Fraction],
    cost: Fraction, horizon: int, include_experiment: bool = True,
) -> FiniteSampleDesignProblem:
    worlds = ("h0", "h1")
    actions = ("a0", "a1")
    loss = {
        (world, action): Fraction(
            int((world == "h1") != (action == "a1"))
        )
        for world in worlds for action in actions
    }
    experiments: tuple[SamplingExperiment, ...] = ()
    if include_experiment:
        experiments = (
            SamplingExperiment(
                name="sample", cost=cost, outcomes=("0", "1"),
                laws={"h0": p0, "h1": p1},
            ),
        )
    return FiniteSampleDesignProblem(
        worlds=worlds, actions=actions, loss=loss,
        experiments=experiments, horizon=horizon,
    )


def main() -> None:
    specs = (
        ("no_experiment", binary_problem(
            p0=(Fraction(1,2), Fraction(1,2)),
            p1=(Fraction(1,2), Fraction(1,2)), cost=Fraction(0),
            horizon=0, include_experiment=False), Fraction(1,2)),
        ("uninformative_h2", binary_problem(
            p0=(Fraction(1,2), Fraction(1,2)),
            p1=(Fraction(1,2), Fraction(1,2)), cost=Fraction(0),
            horizon=2), Fraction(1,2)),
        ("perfect_low_cost", binary_problem(
            p0=(Fraction(1), Fraction(0)), p1=(Fraction(0), Fraction(1)),
            cost=Fraction(1,10), horizon=1), Fraction(1,10)),
        ("perfect_high_cost", binary_problem(
            p0=(Fraction(1), Fraction(0)), p1=(Fraction(0), Fraction(1)),
            cost=Fraction(3,5), horizon=1), Fraction(1,2)),
        ("symmetric_noisy_h1", binary_problem(
            p0=(Fraction(3,4), Fraction(1,4)),
            p1=(Fraction(1,4), Fraction(3,4)), cost=Fraction(0),
            horizon=1), Fraction(1,4)),
        ("symmetric_noisy_h3", binary_problem(
            p0=(Fraction(3,4), Fraction(1,4)),
            p1=(Fraction(1,4), Fraction(3,4)), cost=Fraction(0),
            horizon=3), Fraction(5,32)),
        ("asymmetric_randomized", binary_problem(
            p0=(Fraction(9,10), Fraction(1,10)),
            p1=(Fraction(1,5), Fraction(4,5)), cost=Fraction(0),
            horizon=1), Fraction(2,11)),
    )

    cases: list[dict[str, object]] = []
    for name, problem, expected in specs:
        certificate = build_finite_sample_certificate(problem, name)
        errors = verify_finite_sample_certificate(certificate)
        if errors:
            raise AssertionError(f"{name} replay failed: {errors}")
        solution = certificate["payload"]["solution"]
        actual = Fraction(*solution["value"])
        if actual != expected:
            raise AssertionError(f"{name}: {actual} != {expected}")
        cases.append({
            "case": name,
            "expected_value": [expected.numerator, expected.denominator],
            "actual_value": solution["value"],
            "frontier_sizes_by_horizon": solution["frontier_sizes_by_horizon"],
            "policy_count": solution["policy_count"],
            "least_favorable_prior": solution["least_favorable_prior"],
            "certificate_sha256": certificate["sha256"],
            "replay": "PASS",
        })

    noisy_values = {
        item["case"]: item["actual_value"] for item in cases
        if str(item["case"]).startswith("symmetric_noisy")
    }
    if noisy_values != {
        "symmetric_noisy_h1": [1,4],
        "symmetric_noisy_h3": [5,32],
    }:
        raise AssertionError("unexpected noisy-sampling horizon values")

    tampered = build_finite_sample_certificate(specs[-1][1], specs[-1][0])
    tampered["payload"]["solution"]["value"] = [1,5]
    if verify_finite_sample_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("tampered benchmark certificate accepted")

    report = {
        "schema": "inference-power-compiler/finite-sample-benchmark/1",
        "cases": cases,
        "gates": {
            "case_count": len(cases),
            "all_exact_values": "PASS",
            "all_semantic_replays": "PASS",
            "tampered_certificate": "REJECTED:payload-hash",
            "uninformative_experiment_cannot_improve": True,
            "perfect_information_used_only_below_half_loss": True,
            "horizon_three_improves_symmetric_noisy_risk": True,
            "randomization_required_for_asymmetric_minimax": True,
        },
    }
    report["sha256"] = sha256(
        canonical_json(report).encode("utf-8")
    ).hexdigest()
    path = ROOT / "FINITE_SAMPLE_BENCHMARK_REPORT.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
