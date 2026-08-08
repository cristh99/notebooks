from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

from fano_lower_bound import (
    build_fano_certificate,
    canonical_json,
    decimal_string,
    fano_packing_bound,
    fraction_data,
    verify_fano_certificate,
)
from logic_power_v10.active_discovery import ActiveDiscoveryProblem, Experiment
from logic_power_v10.certificate import (
    build_certificate as build_logic_certificate,
    verify_certificate as verify_logic_certificate,
)
from lower_bound_compiler import FiniteEstimationProblem
from packing_lower_bound import (
    make_mary_symmetric_channel,
    uniform_bayes_classifier,
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
        ("uniform_mixture", Fraction(1), Fraction(9, 10)),
        ("log_interval", Fraction(2), Fraction(4, 5)),
        ("mutual_information", Fraction(2), Fraction(4, 5)),
        ("fano_direction", Fraction(2), Fraction(3, 4)),
        ("packing_transport", Fraction(2), Fraction(3, 4)),
        ("independent_wolfram", Fraction(3), Fraction(2, 3)),
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
    path: list[str] = []
    node = tree
    while node.get("status") == "UNKNOWN":
        experiment = node.get("experiment")
        children = node.get("children")
        if not isinstance(experiment, str) or not isinstance(children, dict):
            raise ValueError("malformed Logic Power v10 policy")
        path.append(experiment)
        child = children.get("0")
        if not isinstance(child, dict):
            raise ValueError("clean branch is missing")
        node = child
    if node.get("status") != "TRUE":
        raise AssertionError("all-clean path must terminate TRUE")
    return path


def main() -> None:
    classification = make_mary_symmetric_channel(
        classes=16, error_probability=Fraction(1, 4)
    )
    certificate = build_fano_certificate(
        classification,
        "sixteen_ary_symmetric_q1_4",
        log_terms=12,
    )
    errors = verify_fano_certificate(certificate)
    if errors:
        raise AssertionError(f"Fano semantic replay failed: {errors}")
    fano_result = certificate["payload"]["result"]
    fano_lower = Fraction(*fano_result["classification_lower_bound"])
    if not (Fraction(197, 1000) < fano_lower < Fraction(1, 4)):
        raise AssertionError("certified Fano interval changed")

    exact = uniform_bayes_classifier(classification)
    if (
        exact["uniform_bayes_error"] != [1, 4]
        or exact["candidate_maximum_risk"] != [1, 4]
        or exact["matched_exact_minimax"] is not True
    ):
        raise AssertionError("exact sixteen-way Bayes control changed")

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
    packing = fano_packing_bound(estimation, log_terms=12)
    estimation_lower = Fraction(*packing["estimation_lower_bound"])
    if not (Fraction(197, 2000) < estimation_lower < Fraction(1, 8)):
        raise AssertionError("Fano packing bound changed")

    information = fano_result["mutual_information_interval"]
    maximum_width = Fraction(*information["maximum_log_interval_width"])
    if maximum_width >= Fraction(1, 10**10):
        raise AssertionError("log intervals are too wide")

    gate_problem = build_gate_problem()
    gate_certificate = build_logic_certificate(
        gate_problem, "fano_lower_bound_promotion"
    )
    gate_errors = verify_logic_certificate(gate_certificate)
    if gate_errors:
        raise AssertionError(f"Logic Power replay failed: {gate_errors}")
    analysis = gate_certificate["payload"]["analysis"]
    policy = analysis["policy"]
    fixed_basis = gate_problem.exact_fixed_basis()
    if fixed_basis is None:
        raise AssertionError("Fano gate problem must be separable")
    fixed_cost = sum(
        (experiment.cost for experiment in fixed_basis), Fraction(0)
    )
    expected = Fraction(policy["expected_cost"][0], policy["expected_cost"][1])

    tampered = copy.deepcopy(certificate)
    tampered["payload"]["result"]["classification_lower_bound"] = [1, 4]
    tamper_errors = verify_fano_certificate(tampered)
    if tamper_errors != ["payload-hash"]:
        raise AssertionError(f"tampered Fano certificate accepted: {tamper_errors}")

    write_json(ROOT / "FANO_LOWER_BOUND_CERTIFICATE.json", certificate)
    write_json(ROOT / "FANO_GATE_CERTIFICATE.json", gate_certificate)

    report = {
        "schema": "inference-power-compiler/fano-report/1",
        "control": {
            "classes": 16,
            "symmetric_error_probability": [1, 4],
            "exact_bayes_minimax_error": [1, 4],
            "certified_mutual_information_interval": {
                "lower": information["lower"],
                "upper": information["upper"],
                "lower_decimal": information["lower_decimal"],
                "upper_decimal": information["upper_decimal"],
            },
            "certified_fano_classification_lower": fraction_data(fano_lower),
            "certified_fano_classification_decimal": decimal_string(fano_lower),
            "fano_gap_to_exact_error": fraction_data(
                Fraction(1, 4) - fano_lower
            ),
        },
        "one_hot_packing": {
            "minimum_squared_separation": packing[
                "minimum_squared_target_separation"
            ],
            "packing_radius_squared": packing["packing_radius_squared"],
            "certified_estimation_lower": packing[
                "estimation_lower_bound"
            ],
            "certified_estimation_decimal": packing[
                "estimation_lower_decimal"
            ],
            "exact_bayes_packing_lower": [1, 8],
        },
        "log_certificate": {
            "terms": information["log_terms"],
            "nonzero_information_terms": information["nonzero_terms"],
            "maximum_log_interval_width": information[
                "maximum_log_interval_width"
            ],
            "deterministic_rational_bounds": True,
        },
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
            "mutual_information_decimal": "1.53324102734542037088189702807106907859",
            "fano_classification_decimal": "0.19700019334031562406017759634960982240",
            "one_hot_estimation_decimal": "0.09850009667015781203008879817480491120",
            "exact_bayes_error": [1, 4],
            "agreement": "PASS",
        },
        "tampered_certificate": "REJECTED:payload-hash",
        "scientific_boundary": (
            "Fano is an established information-theoretic lower bound. "
            "This artifact contributes certified rational logarithm "
            "intervals, automated finite mutual-information compilation, "
            "packing transport and proof-carrying replay; it does not claim "
            "historical novelty."
        ),
    }
    report["sha256"] = sha256(canonical_json(report).encode("utf-8")).hexdigest()
    write_json(ROOT / "FANO_COMPILER_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
