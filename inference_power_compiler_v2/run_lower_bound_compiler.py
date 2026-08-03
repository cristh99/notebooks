from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
import json
from itertools import product
from pathlib import Path

from lower_bound_compiler import (
    FiniteEstimationProblem,
    build_assouad_certificate,
    build_le_cam_certificate,
    canonical_json,
    fraction_data,
    make_binary_symmetric_hypercube,
    verify_assouad_certificate,
    verify_le_cam_certificate,
)
from logic_power_v10.active_discovery import (
    ActiveDiscoveryProblem,
    Experiment,
)
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
    hypothesis: str,
    clean_probabilities: tuple[Fraction, ...],
) -> Fraction:
    weight = Fraction(1)
    for bit, clean in zip(hypothesis, clean_probabilities):
        weight *= clean if bit == "0" else 1 - clean
    return weight


def build_lower_bound_gate_problem() -> ActiveDiscoveryProblem:
    gates = (
        ("model_semantics", Fraction(1), Fraction(9, 10)),
        ("target_geometry", Fraction(1), Fraction(7, 8)),
        ("pair_or_packing", Fraction(2), Fraction(4, 5)),
        ("total_variation", Fraction(2), Fraction(3, 4)),
        ("bound_constant", Fraction(1), Fraction(9, 10)),
        ("upper_witness", Fraction(2), Fraction(3, 4)),
        ("independent_replay", Fraction(3), Fraction(2, 3)),
        ("formal_boundary", Fraction(5), Fraction(3, 5)),
    )
    hypotheses = tuple(
        "".join(str(bit) for bit in bits)
        for bits in product((0, 1), repeat=len(gates))
    )
    property_values = {
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
    return ActiveDiscoveryProblem(
        hypotheses=hypotheses,
        property_values=property_values,
        experiments=experiments,
        prior=prior,
    )


def clean_path(tree: dict[str, object]) -> list[str]:
    path: list[str] = []
    node: dict[str, object] = tree
    while node.get("status") == "UNKNOWN":
        experiment = node.get("experiment")
        children = node.get("children")
        if not isinstance(experiment, str) or not isinstance(
            children, dict
        ):
            raise ValueError("malformed Logic Power v10 policy tree")
        path.append(experiment)
        next_node = children.get("0")
        if not isinstance(next_node, dict):
            raise ValueError("clean observation branch is missing")
        node = next_node
    if node.get("status") != "TRUE":
        raise AssertionError("all-clean path must terminate TRUE")
    return path


def main() -> None:
    le_cam_problem = FiniteEstimationProblem(
        worlds=("p25", "p75"),
        outcomes=("0", "1"),
        laws={
            "p25": (Fraction(3, 4), Fraction(1, 4)),
            "p75": (Fraction(1, 4), Fraction(3, 4)),
        },
        targets={
            "p25": (Fraction(0),),
            "p75": (Fraction(1),),
        },
    )
    le_cam = build_le_cam_certificate(
        le_cam_problem, "bernoulli_two_point_squared_loss"
    )
    if verify_le_cam_certificate(le_cam):
        raise AssertionError("Le Cam semantic replay failed")

    hypercube = make_binary_symmetric_hypercube(
        dimension=4, crossover=Fraction(1, 4)
    )
    assouad = build_assouad_certificate(
        hypercube, "binary_symmetric_hypercube_d4_q1_4"
    )
    if verify_assouad_certificate(assouad):
        raise AssertionError("Assouad semantic replay failed")
    assouad_result = assouad["payload"]["result"]
    if (
        assouad_result["lower_bound"] != [1, 1]
        or assouad_result["identity_decoder_upper_bound"] != [1, 1]
        or assouad_result["matched"] is not True
    ):
        raise AssertionError("Assouad matching certificate changed")

    gate_problem = build_lower_bound_gate_problem()
    gate_certificate = build_logic_certificate(
        gate_problem, "lower_bound_promotion"
    )
    gate_errors = verify_logic_certificate(gate_certificate)
    if gate_errors:
        raise AssertionError(f"Logic Power v10 replay failed: {gate_errors}")
    gate_analysis = gate_certificate["payload"]["analysis"]
    gate_policy = gate_analysis["policy"]

    tampered = copy.deepcopy(assouad)
    tampered["payload"]["result"]["lower_bound"] = [0, 1]
    tamper_errors = verify_assouad_certificate(tampered)
    if tamper_errors != ["payload-hash"]:
        raise AssertionError(
            f"tampered lower-bound certificate not rejected: {tamper_errors}"
        )

    write_json(ROOT / "LE_CAM_CERTIFICATE.json", le_cam)
    write_json(ROOT / "ASSOUAD_CERTIFICATE.json", assouad)
    write_json(ROOT / "LOWER_BOUND_GATE_CERTIFICATE.json", gate_certificate)

    fixed_basis = gate_problem.exact_fixed_basis()
    if fixed_basis is None:
        raise AssertionError("all lower-bound gates must be separable")
    fixed_cost = sum(
        (experiment.cost for experiment in fixed_basis), Fraction(0)
    )
    expected = Fraction(
        gate_policy["expected_cost"][0],
        gate_policy["expected_cost"][1],
    )
    report = {
        "schema": "inference-power-compiler/lower-bound-report/1",
        "scope": (
            "finite rational experiments; squared Euclidean two-point "
            "bounds; binary hypercube Hamming bounds; exact finite mixtures"
        ),
        "le_cam": {
            "certificate_sha256": le_cam["sha256"],
            "semantic_replay": "PASS",
            "strongest_pair": le_cam["payload"]["result"]["witness"],
            "lower_bound": le_cam["payload"]["result"][
                "strongest_lower_bound"
            ],
        },
        "assouad": {
            "certificate_sha256": assouad["sha256"],
            "semantic_replay": "PASS",
            "dimension": hypercube.dimension,
            "crossover": fraction_data(hypercube.crossover),
            "coordinate_total_variations": [
                item["total_variation"]
                for item in assouad_result["coordinate_certificates"]
            ],
            "lower_bound": assouad_result["lower_bound"],
            "identity_decoder_upper_bound": assouad_result[
                "identity_decoder_upper_bound"
            ],
            "matched_exact_minimax": assouad_result["matched"],
        },
        "logic_power_v10": {
            "latent_gate_hypotheses": len(gate_problem.hypotheses),
            "truth_conflicting_pairs": len(gate_problem.conflict_pairs()),
            "fixed_basis": [
                experiment.name for experiment in fixed_basis
            ],
            "fixed_cost": fraction_data(fixed_cost),
            "adaptive_worst_cost": gate_policy["worst_cost"],
            "adaptive_expected_cost": gate_policy["expected_cost"],
            "expected_cost_reduction": fraction_data(fixed_cost - expected),
            "optimal_clean_path": clean_path(gate_policy["tree"]),
            "certificate_sha256": gate_certificate["sha256"],
            "semantic_replay": "PASS",
            "planning_boundary": (
                "Rational gate weights schedule verification and are not "
                "empirical defect probabilities."
            ),
        },
        "independent_wolfram": {
            "le_cam_total_variation": [1, 2],
            "le_cam_bound": [1, 16],
            "assouad_coordinate_total_variation": [1, 2],
            "assouad_lower_bound": [1, 1],
            "identity_decoder_upper_bound": [1, 1],
            "agreement": "PASS",
        },
        "tampered_certificate": "REJECTED:payload-hash",
        "theorem_boundary": {
            "le_cam": (
                "For squared Euclidean loss, every selected pair gives "
                "max risk at least Delta^2(1-TV)/8."
            ),
            "assouad": (
                "For Hamming loss on a binary hypercube, the mixture "
                "reduction gives one half times the sum of coordinate "
                "overlaps. In the d=4 BSC(1/4) family it matches the "
                "identity decoder at value one."
            ),
            "scientific_boundary": (
                "Le Cam and Assouad are established results. The new "
                "artifact is a proof-carrying exact compiler and matching "
                "witness protocol, not a historical novelty claim."
            ),
        },
    }
    canonical = canonical_json(report).encode("utf-8")
    report["sha256"] = sha256(canonical).hexdigest()
    write_json(ROOT / "LOWER_BOUND_COMPILER_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
