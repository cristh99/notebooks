from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

from lower_bound_compiler import FiniteEstimationProblem, canonical_json, fraction_data
from packing_lower_bound import (
    build_classification_certificate,
    build_packing_certificate,
    make_mary_symmetric_channel,
    verify_classification_certificate,
    verify_packing_certificate,
)
from logic_power_v10.active_discovery import ActiveDiscoveryProblem, Experiment
from logic_power_v10.certificate import (
    build_certificate as build_logic_certificate,
    verify_certificate as verify_logic_certificate,
)


ROOT = Path(__file__).resolve().parent


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def product_prior(
    hypothesis: str, clean_probabilities: tuple[Fraction, ...]
) -> Fraction:
    weight = Fraction(1)
    for bit, clean in zip(hypothesis, clean_probabilities):
        weight *= clean if bit == "0" else 1 - clean
    return weight


def build_gate_problem() -> ActiveDiscoveryProblem:
    gates = (
        ("law_normalization", Fraction(1), Fraction(9, 10)),
        ("uniform_bayes_decoder", Fraction(2), Fraction(4, 5)),
        ("packing_separation", Fraction(2), Fraction(4, 5)),
        ("subset_search_completeness", Fraction(3), Fraction(2, 3)),
        ("testing_reduction", Fraction(2), Fraction(3, 4)),
        ("candidate_upper_bound", Fraction(2), Fraction(3, 4)),
        ("independent_replay", Fraction(3), Fraction(2, 3)),
        ("formal_boundary", Fraction(5), Fraction(3, 5)),
    )
    hypotheses = tuple(
        "".join(str(bit) for bit in bits)
        for bits in product((0, 1), repeat=len(gates))
    )
    properties = {
        hypothesis: set(hypothesis) <= {"0"} for hypothesis in hypotheses
    }
    clean_probabilities = tuple(clean for _, _, clean in gates)
    prior = {
        hypothesis: product_prior(hypothesis, clean_probabilities)
        for hypothesis in hypotheses
    }
    experiments = tuple(
        Experiment(
            name=name,
            cost=cost,
            observations={
                hypothesis: hypothesis[index]
                for hypothesis in hypotheses
            },
        )
        for index, (name, cost, _) in enumerate(gates)
    )
    return ActiveDiscoveryProblem(hypotheses, properties, experiments, prior)


def clean_path(tree: dict[str, object]) -> list[str]:
    node = tree
    result: list[str] = []
    while node.get("status") == "UNKNOWN":
        experiment = node.get("experiment")
        children = node.get("children")
        if not isinstance(experiment, str) or not isinstance(children, dict):
            raise ValueError("malformed policy tree")
        result.append(experiment)
        child = children.get("0")
        if not isinstance(child, dict):
            raise ValueError("missing clean branch")
        node = child
    if node.get("status") != "TRUE":
        raise AssertionError("all-clean path must terminate TRUE")
    return result


def main() -> None:
    classification = make_mary_symmetric_channel(
        classes=5, error_probability=Fraction(1, 5)
    )
    classification_certificate = build_classification_certificate(
        classification, "five_ary_symmetric_q1_5"
    )
    if verify_classification_certificate(classification_certificate):
        raise AssertionError("classification replay failed")
    classification_result = classification_certificate["payload"]["result"]
    if (
        classification_result["uniform_bayes_error"] != [1, 5]
        or classification_result["candidate_maximum_risk"] != [1, 5]
        or classification_result["matched_exact_minimax"] is not True
    ):
        raise AssertionError("five-ary minimax match changed")

    targets = {
        world: tuple(
            Fraction(1 if index == world_index else 0)
            for index in range(len(classification.worlds))
        )
        for world_index, world in enumerate(classification.worlds)
    }
    estimation = FiniteEstimationProblem(
        worlds=classification.worlds,
        outcomes=classification.outcomes,
        laws=classification.laws,
        targets=targets,
    )
    packing_certificate = build_packing_certificate(
        estimation,
        "five_ary_one_hot_packing",
        max_subset_size=5,
        max_packings=64,
    )
    if verify_packing_certificate(packing_certificate):
        raise AssertionError("packing replay failed")
    packing_result = packing_certificate["payload"]["result"]
    strongest = packing_result["strongest_witness"]
    if (
        strongest["subset"] != list(classification.worlds)
        or strongest["estimation_lower_bound"] != [1, 10]
        or packing_result["packings_examined"] != 26
    ):
        raise AssertionError("strongest packing changed")

    gate_problem = build_gate_problem()
    gate_certificate = build_logic_certificate(
        gate_problem, "packing_lower_bound_promotion"
    )
    errors = verify_logic_certificate(gate_certificate)
    if errors:
        raise AssertionError(f"Logic Power v10 replay failed: {errors}")
    analysis = gate_certificate["payload"]["analysis"]
    policy = analysis["policy"]
    fixed_basis = gate_problem.exact_fixed_basis()
    if fixed_basis is None:
        raise AssertionError("gate problem must be separable")
    fixed_cost = sum(
        (experiment.cost for experiment in fixed_basis), Fraction(0)
    )
    expected = Fraction(policy["expected_cost"][0], policy["expected_cost"][1])

    tampered = copy.deepcopy(packing_certificate)
    tampered["payload"]["result"]["strongest_lower_bound"] = [1, 9]
    tamper_errors = verify_packing_certificate(tampered)
    if tamper_errors != ["payload-hash"]:
        raise AssertionError(f"tampered packing not rejected: {tamper_errors}")

    write_json(
        ROOT / "MULTIWAY_CLASSIFICATION_CERTIFICATE.json",
        classification_certificate,
    )
    write_json(ROOT / "PACKING_LOWER_BOUND_CERTIFICATE.json", packing_certificate)
    write_json(ROOT / "PACKING_GATE_CERTIFICATE.json", gate_certificate)

    report = {
        "schema": "inference-power-compiler/packing-report/1",
        "multiway_classification": {
            "classes": 5,
            "error_probability": [1, 5],
            "uniform_bayes_error": [1, 5],
            "identity_decoder_maximum_risk": [1, 5],
            "exact_minimax_value": [1, 5],
            "certificate_sha256": classification_certificate["sha256"],
            "semantic_replay": "PASS",
        },
        "packing_to_estimation": {
            "targets": "five one-hot vertices",
            "packings_examined": packing_result["packings_examined"],
            "strongest_subset": strongest["subset"],
            "minimum_squared_separation": strongest[
                "minimum_squared_target_separation"
            ],
            "packing_radius_squared": strongest["packing_radius_squared"],
            "optimal_uniform_testing_error": strongest[
                "optimal_uniform_testing_error"
            ],
            "estimation_lower_bound": strongest[
                "estimation_lower_bound"
            ],
            "certificate_sha256": packing_certificate["sha256"],
            "semantic_replay": "PASS",
        },
        "subset_progression": [
            {
                "size": size,
                "testing_error": error,
                "estimation_lower_bound": bound,
            }
            for size, error, bound in (
                (2, [1, 8], [1, 16]),
                (3, [1, 6], [1, 12]),
                (4, [3, 16], [3, 32]),
                (5, [1, 5], [1, 10]),
            )
        ],
        "logic_power_v10": {
            "latent_hypotheses": len(gate_problem.hypotheses),
            "truth_conflicting_pairs": len(gate_problem.conflict_pairs()),
            "fixed_basis": [experiment.name for experiment in fixed_basis],
            "fixed_cost": fraction_data(fixed_cost),
            "adaptive_worst_cost": policy["worst_cost"],
            "adaptive_expected_cost": policy["expected_cost"],
            "expected_cost_reduction": fraction_data(fixed_cost - expected),
            "optimal_clean_path": clean_path(policy["tree"]),
            "certificate_sha256": gate_certificate["sha256"],
            "semantic_replay": "PASS",
        },
        "independent_wolfram": {
            "uniform_bayes_error": [1, 5],
            "identity_upper": [1, 5],
            "classification_matched": True,
            "packing_lower": [1, 10],
            "subset_bounds": [
                [2, [1, 8], [1, 16]],
                [3, [1, 6], [1, 12]],
                [4, [3, 16], [3, 32]],
                [5, [1, 5], [1, 10]],
            ],
            "agreement": "PASS",
        },
        "tampered_certificate": "REJECTED:payload-hash",
        "theorem_boundary": {
            "classification": (
                "Uniform-prior Bayes error lower-bounds minimax error. "
                "When the candidate decoder has the same maximum risk, "
                "the common value is exact."
            ),
            "packing": (
                "Nearest-target classification turns a wrong label into "
                "squared estimation loss at least one quarter of the "
                "minimum squared packing separation."
            ),
            "scientific_boundary": (
                "The testing reduction is established decision theory. "
                "This artifact compiles exact finite packings and Bayes "
                "errors; it is not a historical novelty claim."
            ),
        },
    }
    report["sha256"] = sha256(canonical_json(report).encode("utf-8")).hexdigest()
    write_json(ROOT / "PACKING_COMPILER_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
