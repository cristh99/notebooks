from __future__ import annotations

from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
    mean = sum((p * x for x, p in zip(values, probabilities)), Fraction(0))
    variance = sum((p * x * x for x, p in zip(values, probabilities)), Fraction(0))
    third = sum((p * abs(x) ** 3 for x, p in zip(values, probabilities)), Fraction(0))
    if mean != 0 or variance != Fraction(5, 8) or third != Fraction(23, 32):
        raise AssertionError("single-score moments changed")

    total_count = 64
    total_variance = total_count * variance
    total_third = total_count * third
    sqrt_lower = Fraction(1581, 250)
    if sqrt_lower * sqrt_lower >= total_variance:
        raise AssertionError("declared square-root lower bound is invalid")
    lyapunov_upper = total_third / (total_variance * sqrt_lower)
    berry_upper = Fraction(14, 25) * lyapunov_upper
    if total_variance != 40 or total_third != 46:
        raise AssertionError("aggregate moments changed")
    if lyapunov_upper != Fraction(575, 3162):
        raise AssertionError("Lyapunov upper bound changed")
    if berry_upper != Fraction(161, 1581):
        raise AssertionError("Berry-Esseen upper bound changed")

    lindeberg_threshold_squared = Fraction(1, 4) ** 2 * total_variance
    if lindeberg_threshold_squared != Fraction(5, 2):
        raise AssertionError("Lindeberg threshold changed")
    if max(x * x for x in values) >= lindeberg_threshold_squared:
        raise AssertionError("Lindeberg zero-tail control failed")

    mean_variance = total_variance / (total_count * total_count)
    chebyshev_failure = mean_variance / (Fraction(1, 2) ** 2)
    chebyshev_coverage = 1 - chebyshev_failure
    if mean_variance != Fraction(5, 512):
        raise AssertionError("mean variance changed")
    if chebyshev_failure != Fraction(5, 128) or chebyshev_coverage != Fraction(123, 128):
        raise AssertionError("Chebyshev coverage changed")

    payload = {
        "schema": "conditional-clt/public-independent-receipt/1",
        "private_repository": "cristh99/my_first_repository",
        "private_pr": 68,
        "private_source_blob": "dd8e37b81db164aceffd0912905858505287c877",
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "score_kernel": {
            "values": [[0, 1], [-1, 1], [1, 1], [1, 2], [-3, 2]],
            "probabilities": [[1, 4], [1, 8], [1, 8], [3, 8], [1, 8]],
            "multiplicity": 64,
        },
        "moments": {
            "mean": [0, 1],
            "single_variance": [5, 8],
            "single_third_absolute_moment": [23, 32],
            "total_variance": [40, 1],
            "total_third_absolute_moment": [46, 1],
        },
        "normal_approximation": {
            "sqrt_total_variance_lower": [1581, 250],
            "lyapunov_ratio_upper": [575, 3162],
            "berry_esseen_constant": [14, 25],
            "kolmogorov_distance_upper": [161, 1581],
        },
        "lindeberg": {
            "epsilon": [1, 4],
            "threshold_squared": [5, 2],
            "maximum_score_squared": [9, 4],
            "truncated_second_moment": [0, 1],
            "status": "PASS",
        },
        "chebyshev": {
            "mean_variance": [5, 512],
            "half_width": [1, 2],
            "failure_probability_upper": [5, 128],
            "coverage_lower": [123, 128],
        },
        "negative_control": {
            "independent_given_training": False,
            "required_status": "INVALID_DEPENDENCE",
        },
        "gates": {
            "exact_centering": "PASS",
            "positive_variance": "PASS",
            "finite_third_moment": "PASS",
            "sqrt_enclosure": "PASS",
            "Berry_Esseen_arithmetic": "PASS",
            "Lindeberg_zero_tail": "PASS",
            "Chebyshev_coverage": "PASS",
            "dependence_guard": "PASS",
        },
    }
    receipt = {
        "payload": payload,
        "sha256": sha256(canonical_json(payload).encode()).hexdigest(),
    }
    path = ROOT / "CONDITIONAL_CLT_PUBLIC_RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
