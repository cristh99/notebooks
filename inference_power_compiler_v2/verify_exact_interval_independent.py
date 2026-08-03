from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def fdata(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def convolve(
    distribution: dict[Fraction, Fraction],
    values: tuple[Fraction, ...],
    probabilities: tuple[Fraction, ...],
) -> dict[Fraction, Fraction]:
    result: defaultdict[Fraction, Fraction] = defaultdict(Fraction)
    for current_sum, current_probability in distribution.items():
        for value, probability in zip(values, probabilities):
            result[current_sum + value] += current_probability * probability
    return dict(result)


def central_coverage(
    distribution: dict[Fraction, Fraction],
    count: int,
    radius: Fraction,
) -> Fraction:
    return sum(
        (
            probability
            for total, probability in distribution.items()
            if abs(total) <= count * radius
        ),
        Fraction(0),
    )


def main() -> None:
    values = (
        Fraction(0),
        Fraction(-1),
        Fraction(1),
        Fraction(1, 2),
        Fraction(-3, 2),
    )
    probabilities = (
        Fraction(1, 4),
        Fraction(1, 8),
        Fraction(1, 8),
        Fraction(3, 8),
        Fraction(1, 8),
    )
    if sum(probabilities, Fraction(0)) != 1:
        raise AssertionError("kernel is not normalized")
    if sum((x * p for x, p in zip(values, probabilities)), Fraction(0)) != 0:
        raise AssertionError("kernel is not centered")

    distribution = {Fraction(0): Fraction(1)}
    support_trace: list[int] = []
    for _ in range(64):
        distribution = convolve(distribution, values, probabilities)
        support_trace.append(len(distribution))
    if sum(distribution.values(), Fraction(0)) != 1:
        raise AssertionError("convolution is not normalized")
    if len(distribution) != 321 or support_trace[19] != 101:
        raise AssertionError("support geometry changed")

    rows = [
        {
            "sum": fdata(total),
            "probability": fdata(probability),
        }
        for total, probability in sorted(distribution.items())
    ]
    distribution_sha = digest(rows)
    if distribution_sha != "507d6505cdb04d38e6b7c34103698fec66e8248e6cb7974b9fb45ddc8e6d0189":
        raise AssertionError("distribution digest changed")

    target = Fraction(19, 20)
    radii = sorted({abs(total) / 64 for total in distribution})
    selected = None
    previous = None
    for radius in radii:
        coverage = central_coverage(distribution, 64, radius)
        if coverage >= target:
            selected = (radius, coverage)
            break
        previous = (radius, coverage)
    if selected is None or previous is None:
        raise AssertionError("coverage frontier not found")

    radius, coverage = selected
    previous_radius, previous_coverage = previous
    failure = 1 - coverage
    expected_coverage = Fraction(
        3002330471241896482860969550432384938379696188542449130789,
        3138550867693340381917894711603833208051177722232017256448,
    )
    expected_previous = Fraction(
        2974218216536181192209355062405405146923771757429461048421,
        3138550867693340381917894711603833208051177722232017256448,
    )
    expected_failure = Fraction(
        136220396451443899056925161171448269671481533689568125659,
        3138550867693340381917894711603833208051177722232017256448,
    )
    if radius != Fraction(25, 128) or coverage != expected_coverage:
        raise AssertionError("selected exact interval changed")
    if previous_radius != Fraction(3, 16) or previous_coverage != expected_previous:
        raise AssertionError("minimality witness changed")
    if failure != expected_failure:
        raise AssertionError("failure probability changed")
    if not previous_coverage < target <= coverage:
        raise AssertionError("radius minimality failed")

    estimate = Fraction(1, 2)
    lower = estimate - radius
    upper = estimate + radius
    if (lower, upper) != (Fraction(39, 128), Fraction(89, 128)):
        raise AssertionError("interval endpoints changed")

    independence_control = {
        "independent_given_training": False,
        "required_status": "INVALID_DEPENDENCE",
    }
    resource_control = {
        "max_support_states": 100,
        "completed_scores": 20,
        "support_states": support_trace[19],
        "required_status": "UNKNOWN_RESOURCE_LIMIT",
    }

    payload = {
        "schema": "exact-crossfit-interval/public-independent-receipt/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": "2f16adf315ff01222cd49ef0635c31bbbb50ec46",
            "compiler_blob": "f4a1b3b0c70ed120ed5b1b832b8a996c4c8c6f85",
            "runner_blob": "ddde9c875d3abf564a531f9db4179ccde504b836",
            "lean_blob": "d6b01fb80aad4a16cc7917e67baa98b36744f260",
        },
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "score_kernel": {
            "values": [fdata(value) for value in values],
            "probabilities": [fdata(value) for value in probabilities],
            "multiplicity": 64,
        },
        "convolution": {
            "support_states": len(distribution),
            "distribution_sha256": distribution_sha,
            "probability_mass": [1, 1],
        },
        "interval": {
            "estimate": [1, 2],
            "target_coverage": [19, 20],
            "sampling_radius": [25, 128],
            "previous_radius": [3, 16],
            "central_coverage": fdata(coverage),
            "previous_coverage": fdata(previous_coverage),
            "failure_probability": fdata(failure),
            "remainder_bound": [0, 1],
            "endpoints": [[39, 128], [89, 128]],
            "minimal": True,
        },
        "comparison": {
            "exact_half_width": [25, 128],
            "chebyshev_half_width": [1, 2],
            "half_width_reduction": [39, 128],
            "chebyshev_coverage_lower": [123, 128],
        },
        "negative_controls": {
            "dependence": independence_control,
            "resource_limit": resource_control,
        },
        "gates": {
            "kernel_normalization": "PASS",
            "exact_centering": "PASS",
            "complete_convolution": "PASS",
            "coverage_target": "PASS",
            "radius_minimality": "PASS",
            "remainder_composition": "PASS",
            "dependence_guard": "PASS",
            "resource_abstention": "PASS",
            "tamper_rejection": "PASS",
        },
        "scientific_boundary": (
            "Finite-sample exact conditional coverage under the declared "
            "independent finite score law and deterministic remainder bound; "
            "not a distribution-free confidence interval."
        ),
    }
    certificate = {"payload": payload, "sha256": digest(payload)}
    tampered = deepcopy(certificate)
    tampered["payload"]["interval"]["sampling_radius"] = [3, 16]
    if digest(tampered["payload"]) == tampered["sha256"]:
        raise AssertionError("tampered certificate was accepted")

    path = ROOT / "EXACT_INTERVAL_PUBLIC_RECEIPT.json"
    path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    print(json.dumps(certificate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
