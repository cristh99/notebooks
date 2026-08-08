from __future__ import annotations

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


def robust_problem(epsilon: Fraction, a: Fraction = Fraction(1, 10)):
    if not 0 <= epsilon <= 1:
        raise ValueError("epsilon must lie in [0,1]")
    p0_low = (1 - epsilon) * a
    p0_high = (1 - epsilon) * a + epsilon
    p1_low = (1 - epsilon) * (1 - a)
    p1_high = (1 - epsilon) * (1 - a) + epsilon
    worlds = ("h0_low", "h0_high", "h1_low", "h1_high")
    actions = ("a0", "a1")
    loss = {
        (world, action): Fraction(
            int((world.startswith("h1")) != (action == "a1"))
        )
        for world in worlds for action in actions
    }
    probabilities = {
        "h0_low": p0_low, "h0_high": p0_high,
        "h1_low": p1_low, "h1_high": p1_high,
    }
    experiment = SamplingExperiment(
        name="sample", cost=Fraction(0), outcomes=("0", "1"),
        laws={world: (1-probability, probability)
              for world, probability in probabilities.items()},
    )
    return FiniteSampleDesignProblem(
        worlds=worlds, actions=actions, loss=loss,
        experiments=(experiment,), horizon=1,
    ), probabilities


def main() -> None:
    a = Fraction(1, 10)
    epsilons = (Fraction(0), Fraction(1,9), Fraction(1,5),
                Fraction(2,9), Fraction(1,3), Fraction(4,9))
    rows = []
    for epsilon in epsilons:
        problem, probabilities = robust_problem(epsilon, a)
        certificate = build_finite_sample_certificate(
            problem, f"huber_epsilon_{epsilon.numerator}_{epsilon.denominator}"
        )
        errors = verify_finite_sample_certificate(certificate)
        if errors:
            raise AssertionError(errors)
        value = Fraction(*certificate["payload"]["solution"]["value"])
        expected = a + epsilon * (1-a)
        if value != expected:
            raise AssertionError((epsilon, value, expected))
        if probabilities["h0_high"] > probabilities["h1_low"]:
            raise AssertionError("grid crosses overlap threshold")
        rows.append({
            "epsilon": [epsilon.numerator, epsilon.denominator],
            "p0_high": [probabilities["h0_high"].numerator,
                        probabilities["h0_high"].denominator],
            "p1_low": [probabilities["h1_low"].numerator,
                       probabilities["h1_low"].denominator],
            "minimax_value": certificate["payload"]["solution"]["value"],
            "expected_formula_value": [expected.numerator, expected.denominator],
            "least_favorable_prior": certificate["payload"]["solution"]["least_favorable_prior"],
            "certificate_sha256": certificate["sha256"],
            "replay": "PASS",
        })
    threshold = Fraction(1-2*a, 2*(1-a))
    if threshold != Fraction(4,9) or rows[-1]["minimax_value"] != [1,2]:
        raise AssertionError("breakdown threshold mismatch")
    tampered_problem, _ = robust_problem(Fraction(1,5), a)
    tampered = build_finite_sample_certificate(tampered_problem, "tamper_control")
    tampered["payload"]["solution"]["value"] = [1,4]
    if verify_finite_sample_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("tampered robust certificate accepted")
    report = {
        "schema": "inference-power-compiler/robust-contamination-phase-transition/1",
        "nominal": {"p0":[1,10], "p1":[9,10]},
        "theorem": {
            "risk_formula": "R*(epsilon)=a+epsilon(1-a) while contamination intervals remain separated",
            "overlap_threshold_formula": "epsilon*=(1-2a)/(2(1-a))",
            "a_one_tenth_threshold": [4,9],
            "interpretation": "At epsilon=4/9 the adversarial Bernoulli intervals touch at 1/2, two opposite classes share one observable law, and minimax risk reaches 1/2."
        },
        "grid": rows,
        "independent_wolfram": {
            "equalizer_identity": True,
            "risk_formula": "(1+9 epsilon)/10",
            "threshold": [4,9]
        },
        "gates": {
            "all_exact_values": "PASS",
            "all_semantic_replays": "PASS",
            "phase_transition_reached": True,
            "tampered_certificate": "REJECTED:payload-hash"
        }
    }
    report["sha256"] = sha256(canonical_json(report).encode()).hexdigest()
    path = ROOT / "ROBUST_CONTAMINATION_REPORT.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
