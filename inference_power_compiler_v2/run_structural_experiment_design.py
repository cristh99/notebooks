from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

from logic_power_v10.certificate import canonical_json

from structural_experiment_design import (
    adaptive_branch_problem,
    build_structural_design_certificate,
    causal_intervention_problem,
    verify_structural_design_certificate,
)

ROOT = Path(__file__).resolve().parent


def _assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(
            f"{label}: expected {expected!r}, got {actual!r}"
        )


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    causal = build_structural_design_certificate(
        causal_intervention_problem(),
        "causal_intervention_separates_observational_twins",
    )
    observational = build_structural_design_certificate(
        causal_intervention_problem(observational_only=True),
        "observational_family_cannot_identify_causal_effect",
    )
    adaptive = build_structural_design_certificate(
        adaptive_branch_problem(),
        "adaptive_structural_experiment_design",
    )

    for name, certificate in (
        ("causal", causal),
        ("observational", observational),
        ("adaptive", adaptive),
    ):
        errors = verify_structural_design_certificate(certificate)
        if errors:
            raise AssertionError(f"{name} replay failed: {errors}")

    causal_result = causal["payload"]["result"]
    observational_result = observational["payload"]["result"]
    adaptive_result = adaptive["payload"]["result"]

    _assert_equal(causal_result["status"], "SOLVED", "causal status")
    _assert_equal(
        causal_result["fixed_basis"],
        ["intervene_A_0"],
        "minimal causal design",
    )
    _assert_equal(
        causal_result["fixed_basis_cost"], [3, 1], "causal design cost"
    )

    _assert_equal(
        observational_result["status"],
        "IMPOSSIBLE",
        "observational impossibility status",
    )
    _assert_equal(
        observational_result["obstruction"],
        ["confounded_no_effect", "direct_positive_effect"],
        "causal nonidentifiability witness",
    )

    _assert_equal(adaptive_result["status"], "SOLVED", "adaptive status")
    _assert_equal(
        adaptive_result["fixed_basis"],
        ["resolve_left", "resolve_right"],
        "adaptive fixed basis",
    )
    _assert_equal(
        adaptive_result["fixed_basis_cost"], [11, 1], "fixed design cost"
    )
    policy = adaptive_result["optimal_policy"]
    _assert_equal(
        policy["tree"]["experiment"],
        "screen_branch",
        "adaptive root experiment",
    )
    _assert_equal(policy["worst_cost"], [8, 1], "adaptive worst cost")
    _assert_equal(
        policy["expected_cost"], [53, 10], "adaptive expected cost"
    )

    tampered = copy.deepcopy(adaptive)
    tampered["payload"]["problem"]["target"]["h0"] = True
    _assert_equal(
        verify_structural_design_certificate(tampered),
        ["payload-hash"],
        "tampered structural certificate rejection",
    )

    fixed_cost = Fraction(*adaptive_result["fixed_basis_cost"])
    expected_cost = Fraction(*policy["expected_cost"])
    worst_cost = Fraction(*policy["worst_cost"])
    expected_reduction = (fixed_cost - expected_cost) / fixed_cost
    worst_reduction = (fixed_cost - worst_cost) / fixed_cost

    report = {
        "schema": (
            "inference-power-compiler/"
            "structural-experiment-design-report/1"
        ),
        "logic_power_v10_source": {
            "branch": "agent/logic-power-v10-active-experiment",
            "head": "ba10d0edc7eb20d499d0481fda2537e782b6efb2",
            "pr": 53,
            "active_discovery_blob": (
                "b1bd56290b3119517817f6f414edb35f9a426cd1"
            ),
            "certificate_blob": (
                "a9c1dd87506df3ec4bff4b0ad86398ab8a49cb5e"
            ),
        },
        "scope": (
            "finite hidden worlds, binary target property, finite candidate "
            "experiments with exact rational observable laws; the oracle "
            "returns a law signature, so this is structural identifiability "
            "and design rather than finite-sample estimation"
        ),
        "causal_identification": {
            "observational_status": observational_result["status"],
            "observational_obstruction": observational_result[
                "obstruction"
            ],
            "interventional_status": causal_result["status"],
            "minimal_interventional_basis": causal_result["fixed_basis"],
            "minimal_cost": causal_result["fixed_basis_cost"],
            "theorem": (
                "The observational law alone cannot identify the causal "
                "effect in the two-world family, while either declared "
                "intervention separates the worlds exactly."
            ),
        },
        "adaptive_design": {
            "fixed_basis": adaptive_result["fixed_basis"],
            "fixed_cost": adaptive_result["fixed_basis_cost"],
            "adaptive_root": policy["tree"]["experiment"],
            "adaptive_worst_cost": policy["worst_cost"],
            "adaptive_expected_cost": policy["expected_cost"],
            "worst_cost_reduction": [
                worst_reduction.numerator,
                worst_reduction.denominator,
            ],
            "expected_cost_reduction": [
                expected_reduction.numerator,
                expected_reduction.denominator,
            ],
            "expected_cost_reduction_percent": round(
                float(100 * expected_reduction), 10
            ),
        },
        "certificates": {
            "causal_sha256": causal["sha256"],
            "observational_impossibility_sha256": observational["sha256"],
            "adaptive_sha256": adaptive["sha256"],
            "all_semantic_replays": "PASS",
            "tampered_certificate": "REJECTED:payload-hash",
        },
    }
    report["sha256"] = sha256(
        canonical_json(report).encode("utf-8")
    ).hexdigest()

    _write(ROOT / "STRUCTURAL_CAUSAL_CERTIFICATE.json", causal)
    _write(
        ROOT / "STRUCTURAL_CAUSAL_IMPOSSIBILITY_CERTIFICATE.json",
        observational,
    )
    _write(ROOT / "STRUCTURAL_ADAPTIVE_DESIGN_CERTIFICATE.json", adaptive)
    _write(ROOT / "STRUCTURAL_EXPERIMENT_DESIGN_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
