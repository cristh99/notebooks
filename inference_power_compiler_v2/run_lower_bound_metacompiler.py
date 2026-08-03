from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

from lower_bound_compiler import (
    FiniteEstimationProblem,
    canonical_json,
    fraction_data,
    make_binary_symmetric_hypercube,
)
from lower_bound_metacompiler import (
    MetaBudget,
    compile_lower_bounds,
    verify_meta_certificate,
)
from logic_power_v10.active_discovery import ActiveDiscoveryProblem, Experiment
from logic_power_v10.certificate import (
    build_certificate as build_logic_certificate,
    verify_certificate as verify_logic_certificate,
)
from packing_lower_bound import make_mary_symmetric_channel


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
        ("problem_semantics", Fraction(1), Fraction(9, 10)),
        ("method_applicability", Fraction(1), Fraction(7, 8)),
        ("resource_accounting", Fraction(2), Fraction(4, 5)),
        ("le_cam_certificate", Fraction(2), Fraction(4, 5)),
        ("packing_certificate", Fraction(2), Fraction(3, 4)),
        ("fano_certificate", Fraction(3), Fraction(2, 3)),
        ("assouad_certificate", Fraction(3), Fraction(2, 3)),
        ("upper_match", Fraction(2), Fraction(3, 4)),
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
    path: list[str] = []
    while node.get("status") == "UNKNOWN":
        experiment = node.get("experiment")
        children = node.get("children")
        if not isinstance(experiment, str) or not isinstance(children, dict):
            raise ValueError("malformed policy tree")
        path.append(experiment)
        child = children.get("0")
        if not isinstance(child, dict):
            raise ValueError("missing clean branch")
        node = child
    if node.get("status") != "TRUE":
        raise AssertionError("all-clean path must terminate TRUE")
    return path


def one_hot_problem(classes: int, error: Fraction) -> FiniteEstimationProblem:
    classification = make_mary_symmetric_channel(classes, error)
    targets = {
        world: tuple(
            Fraction(1 if index == world_index else 0)
            for index in range(classes)
        )
        for world_index, world in enumerate(classification.worlds)
    }
    return FiniteEstimationProblem(
        classification.worlds,
        classification.outcomes,
        classification.laws,
        targets,
    )


def hypercube_problem(dimension: int, crossover: Fraction):
    hypercube = make_binary_symmetric_hypercube(dimension, crossover)
    targets = {
        world: tuple(Fraction(int(bit)) for bit in world)
        for world in hypercube.worlds
    }
    problem = FiniteEstimationProblem(
        hypercube.worlds,
        hypercube.outcomes,
        hypercube.laws,
        targets,
    )
    return problem, hypercube


def main() -> None:
    small = one_hot_problem(5, Fraction(1, 5))
    small_certificate = compile_lower_bounds(
        small,
        "five_class_exact_selection",
        budget=MetaBudget(
            maximum_exact_packings=64,
            maximum_exact_subset_size=5,
            fano_log_terms=12,
        ),
    )
    if verify_meta_certificate(small_certificate):
        raise AssertionError("small metacertificate replay failed")
    small_payload = small_certificate["payload"]
    if (
        small_payload["selected_method"] != "exact_finite_packing"
        or small_payload["selected_lower_bound"] != [1, 10]
        or small_payload["verdict"] != "LOWER_BOUND"
    ):
        raise AssertionError("small exact method selection changed")

    large = one_hot_problem(16, Fraction(1, 4))
    large_certificate = compile_lower_bounds(
        large,
        "sixteen_class_resource_selection",
        budget=MetaBudget(
            maximum_exact_packings=100,
            maximum_exact_subset_size=8,
            fano_log_terms=12,
        ),
    )
    if verify_meta_certificate(large_certificate):
        raise AssertionError("large metacertificate replay failed")
    large_payload = large_certificate["payload"]
    if (
        large_payload["selected_method"] != "certified_fano"
        or Fraction(*large_payload["selected_lower_bound"])
        <= Fraction(197, 2000)
    ):
        raise AssertionError("large Fano selection changed")
    packing_status = next(
        item["status"]
        for item in large_payload["methods"]
        if item["method"] == "exact_finite_packing"
    )
    if packing_status != "SKIPPED_RESOURCE":
        raise AssertionError("large exact packing must abstain by resource")

    cube_problem, cube = hypercube_problem(4, Fraction(1, 4))
    cube_certificate = compile_lower_bounds(
        cube_problem,
        "hypercube_exact_match",
        budget=MetaBudget(
            maximum_exact_packings=100,
            maximum_exact_subset_size=8,
            fano_log_terms=12,
        ),
        hypercube=cube,
        candidate_upper_bound=Fraction(1),
    )
    if verify_meta_certificate(cube_certificate, hypercube=cube):
        raise AssertionError("hypercube metacertificate replay failed")
    cube_payload = cube_certificate["payload"]
    if (
        cube_payload["selected_method"] != "assouad_hypercube"
        or cube_payload["selected_lower_bound"] != [1, 1]
        or cube_payload["candidate_upper_bound"] != [1, 1]
        or cube_payload["verdict"] != "MATCHED"
    ):
        raise AssertionError("hypercube exact match changed")

    gate_problem = build_gate_problem()
    gate_certificate = build_logic_certificate(
        gate_problem, "lower_bound_metacompiler_promotion"
    )
    gate_errors = verify_logic_certificate(gate_certificate)
    if gate_errors:
        raise AssertionError(f"Logic Power v10 replay failed: {gate_errors}")
    analysis = gate_certificate["payload"]["analysis"]
    policy = analysis["policy"]
    fixed_basis = gate_problem.exact_fixed_basis()
    if fixed_basis is None:
        raise AssertionError("metacompiler gates must be separable")
    fixed_cost = sum(
        (experiment.cost for experiment in fixed_basis), Fraction(0)
    )
    expected = Fraction(policy["expected_cost"][0], policy["expected_cost"][1])

    tampered = copy.deepcopy(cube_certificate)
    tampered["payload"]["selected_method"] = "certified_fano"
    tamper_errors = verify_meta_certificate(tampered, hypercube=cube)
    if tamper_errors != ["payload-hash"]:
        raise AssertionError(f"tampered meta certificate accepted: {tamper_errors}")

    write_json(ROOT / "META_SMALL_CERTIFICATE.json", small_certificate)
    write_json(ROOT / "META_LARGE_CERTIFICATE.json", large_certificate)
    write_json(ROOT / "META_HYPERCUBE_CERTIFICATE.json", cube_certificate)
    write_json(ROOT / "META_GATE_CERTIFICATE.json", gate_certificate)

    report = {
        "schema": "inference-power-compiler/lower-bound-metacompiler-report/1",
        "cases": {
            "small_exact": {
                "worlds": 5,
                "selected_method": small_payload["selected_method"],
                "selected_lower_bound": small_payload[
                    "selected_lower_bound"
                ],
                "method_summary": small_payload["methods"],
                "certificate_sha256": small_certificate["sha256"],
            },
            "large_resource_bounded": {
                "worlds": 16,
                "selected_method": large_payload["selected_method"],
                "selected_lower_bound": large_payload[
                    "selected_lower_bound"
                ],
                "exact_packing_status": packing_status,
                "method_summary": large_payload["methods"],
                "certificate_sha256": large_certificate["sha256"],
            },
            "hypercube_matched": {
                "worlds": 16,
                "selected_method": cube_payload["selected_method"],
                "selected_lower_bound": cube_payload[
                    "selected_lower_bound"
                ],
                "candidate_upper_bound": cube_payload[
                    "candidate_upper_bound"
                ],
                "verdict": cube_payload["verdict"],
                "method_summary": cube_payload["methods"],
                "certificate_sha256": cube_certificate["sha256"],
            },
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
        "tampered_certificate": "REJECTED:payload-hash",
        "power_gain": (
            "The compiler chooses an exact packing when affordable, Fano "
            "when enumeration exceeds budget, and Assouad when certified "
            "hypercube structure yields a stronger exact match."
        ),
        "scientific_boundary": (
            "Method selection is exact inside the declared finite methods, "
            "metadata and resource bounds. It is not a completeness theorem "
            "for every statistical lower-bound technique."
        ),
    }
    report["sha256"] = sha256(canonical_json(report).encode("utf-8")).hexdigest()
    write_json(ROOT / "LOWER_BOUND_METACOMPILER_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
