from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from logic_power_v10.active_discovery import ActiveDiscoveryProblem, Experiment
from logic_power_v10.certificate import build_certificate, verify_certificate


def experiment(name: str, cost: int, left: str, right: str) -> Experiment:
    return Experiment(
        name=name,
        cost=Fraction(cost),
        observations={
            "compression_specialist": left,
            "broad_data_science_power": right,
        },
    )


def main() -> None:
    problem = ActiveDiscoveryProblem(
        hypotheses=(
            "compression_specialist",
            "broad_data_science_power",
        ),
        property_values={
            "compression_specialist": False,
            "broad_data_science_power": True,
        },
        experiments=(
            experiment("more_compression_seeds", 1, "PASS", "PASS"),
            experiment("compression_prior_art_audit", 2, "KNOWN", "KNOWN"),
            experiment("safety_router_private_split", 3, "FAIL", "PASS"),
        ),
        prior={
            "compression_specialist": Fraction(1, 2),
            "broad_data_science_power": Fraction(1, 2),
        },
    )
    certificate = build_certificate(problem, "cross-domain-data-science-power")
    errors = verify_certificate(certificate)
    if errors:
        raise SystemExit(f"certificate replay failed: {errors}")
    policy = certificate["payload"]["analysis"]["policy"]
    basis = certificate["payload"]["analysis"]["fixed_basis"]
    if not policy["exact"]:
        raise SystemExit("the original Logic Power v10 returned no exact policy")
    if policy["tree"]["experiment"] != "safety_router_private_split":
        raise SystemExit(f"unexpected first experiment: {policy['tree']}")
    if basis != ["safety_router_private_split"]:
        raise SystemExit(f"unexpected fixed basis: {basis}")

    receipt = {
        "schema": "data-science-god-level/safety-router-logic-plan/1",
        "logic_power_v10_private_head": (
            "ba10d0edc7eb20d499d0481fda2537e782b6efb2"
        ),
        "previous_external_gate": {
            "task": "AutoLab adaptive_compression",
            "run": 30828345539,
            "weighted_candidate_bpb": 3.5266205224273532,
            "public_reference_bpb": 3.8,
        },
        "remaining_hypotheses": [
            "compression_specialist",
            "broad_data_science_power",
        ],
        "selected_experiment": "safety_router_private_split",
        "rejected_low_power_experiments": [
            "more_compression_seeds",
            "compression_prior_art_audit",
        ],
        "certificate": certificate,
    }
    Path("logic-plan-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
