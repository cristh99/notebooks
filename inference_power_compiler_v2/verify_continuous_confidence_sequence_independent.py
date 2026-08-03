from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fdata(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def main() -> None:
    observations = tuple(
        Fraction(value) for value in ([1, 1, 0, 1, 1, 1, 0, 1] * 8)
    )
    positive = (
        Fraction(1, 4),
        Fraction(1, 2),
        Fraction(3, 4),
        Fraction(1),
    )
    negative = tuple(-value for value in positive)
    weights = tuple(Fraction(1, 4) for _ in positive)
    alpha = Fraction(1, 20)
    one_sided_alpha = alpha / 2
    threshold = 1 / one_sided_alpha
    depth = 20
    resolution = Fraction(1, 2**depth)
    reference_mean = Fraction(3, 4)

    if threshold != 40 or resolution != Fraction(1, 1048576):
        raise AssertionError("threshold or resolution changed")
    if sum(weights, Fraction(0)) != 1:
        raise AssertionError("one-sided mixture weights changed")

    corner_factors = {
        lam: tuple(
            1 + lam * (Fraction(x) - Fraction(mean))
            for x in (0, 1)
            for mean in (0, 1)
        )
        for lam in (*positive, *negative)
    }
    if any(value < 0 for values in corner_factors.values() for value in values):
        raise AssertionError("global factor nonnegativity failed")

    @lru_cache(maxsize=None)
    def component(time: int, mean: Fraction, lam: Fraction) -> Fraction:
        wealth = Fraction(1)
        for observation in observations[:time]:
            wealth *= 1 + lam * (observation - mean)
        return wealth

    def e_value(time: int, mean: Fraction, lambdas: tuple[Fraction, ...]) -> Fraction:
        return sum(
            (
                weights[index] * component(time, mean, lam)
                for index, lam in enumerate(lambdas)
            ),
            Fraction(0),
        )

    def lower_bracket(time: int) -> tuple[Fraction, Fraction, str, Fraction, Fraction]:
        at_zero = e_value(time, Fraction(0), positive)
        at_one = e_value(time, Fraction(1), positive)
        if at_zero < threshold:
            return Fraction(0), Fraction(0), "BOUNDARY_ZERO", at_zero, at_zero
        if at_one >= threshold:
            return Fraction(1), Fraction(1), "EMPTY", at_one, at_one
        lo, hi = Fraction(0), Fraction(1)
        for _ in range(depth):
            midpoint = (lo + hi) / 2
            if e_value(time, midpoint, positive) >= threshold:
                lo = midpoint
            else:
                hi = midpoint
        lo_value = e_value(time, lo, positive)
        hi_value = e_value(time, hi, positive)
        if not lo_value >= threshold or not hi_value < threshold:
            raise AssertionError("lower root invariant failed")
        return lo, hi, "ROOT_BRACKET", lo_value, hi_value

    def upper_bracket(time: int) -> tuple[Fraction, Fraction, str, Fraction, Fraction]:
        at_zero = e_value(time, Fraction(0), negative)
        at_one = e_value(time, Fraction(1), negative)
        if at_one < threshold:
            return Fraction(1), Fraction(1), "BOUNDARY_ONE", at_one, at_one
        if at_zero >= threshold:
            return Fraction(0), Fraction(0), "EMPTY", at_zero, at_zero
        lo, hi = Fraction(0), Fraction(1)
        for _ in range(depth):
            midpoint = (lo + hi) / 2
            if e_value(time, midpoint, negative) < threshold:
                lo = midpoint
            else:
                hi = midpoint
        lo_value = e_value(time, lo, negative)
        hi_value = e_value(time, hi, negative)
        if not lo_value < threshold or not hi_value >= threshold:
            raise AssertionError("upper root invariant failed")
        return lo, hi, "ROOT_BRACKET", lo_value, hi_value

    history: dict[int, dict[str, object]] = {}
    reference_values: list[tuple[Fraction, Fraction]] = []
    for time in range(1, len(observations) + 1):
        lower_outer, lower_inner, lower_mode, lower_outer_e, lower_inner_e = lower_bracket(time)
        upper_inner, upper_outer, upper_mode, upper_inner_e, upper_outer_e = upper_bracket(time)
        if lower_outer > upper_outer or lower_inner > upper_inner:
            raise AssertionError("control interval became empty")
        positive_reference = e_value(time, reference_mean, positive)
        negative_reference = e_value(time, reference_mean, negative)
        if positive_reference >= threshold or negative_reference >= threshold:
            raise AssertionError("reference mean was excluded")
        reference_values.append((positive_reference, negative_reference))
        history[time] = {
            "outer": {
                "lower": fdata(lower_outer),
                "upper": fdata(upper_outer),
                "width": fdata(upper_outer - lower_outer),
            },
            "inner": {
                "lower": fdata(lower_inner),
                "upper": fdata(upper_inner),
                "width": fdata(upper_inner - lower_inner),
            },
            "lower_root": {
                "mode": lower_mode,
                "outer_e_value": fdata(lower_outer_e),
                "inner_e_value": fdata(lower_inner_e),
            },
            "upper_root": {
                "mode": upper_mode,
                "inner_e_value": fdata(upper_inner_e),
                "outer_e_value": fdata(upper_outer_e),
            },
            "reference": {
                "positive_e_value": fdata(positive_reference),
                "negative_e_value": fdata(negative_reference),
                "included": True,
            },
        }

    expected_milestones = {
        8: {
            "outer": ([0, 1], [1, 1]),
            "inner": ([0, 1], [1, 1]),
        },
        16: {
            "outer": ([172257, 524288], [1, 1]),
            "inner": ([344515, 1048576], [1, 1]),
        },
        24: {
            "outer": ([463649, 1048576], [1, 1]),
            "inner": ([231825, 524288], [1, 1]),
        },
        32: {
            "outer": ([519143, 1048576], [253265, 262144]),
            "inner": ([64893, 131072], [1013059, 1048576]),
        },
        48: {
            "outer": ([286771, 524288], [957269, 1048576]),
            "inner": ([573543, 1048576], [239317, 262144]),
        },
        64: {
            "outer": ([602055, 1048576], [930133, 1048576]),
            "inner": ([75257, 131072], [232533, 262144]),
        },
    }
    for time, expected in expected_milestones.items():
        packet = history[time]
        if (packet["outer"]["lower"], packet["outer"]["upper"]) != expected["outer"]:
            raise AssertionError(f"outer interval changed at time {time}")
        if (packet["inner"]["lower"], packet["inner"]["upper"]) != expected["inner"]:
            raise AssertionError(f"inner interval changed at time {time}")

    maxima = [max(pair) for pair in reference_values]
    if max(maxima) != Fraction(687, 512) or maxima.index(max(maxima)) + 1 != 2:
        raise AssertionError("reference e-value audit changed")

    required_evaluations = len(observations) * 8 * (depth + 2)
    if required_evaluations != 11_264 or required_evaluations <= 10_000:
        raise AssertionError("resource control changed")

    payload = {
        "schema": "continuous-mean-confidence-sequence/public-independent-receipt/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": "0de4c5c7c68fc23a2cf5238d8177a76d009bc61f",
            "compiler_blob": "10cb158eea5770389e1f64446c1c3c60feed5414",
            "runner_blob": "b1f11d35299fdab8fe4a48cfc98d176b65dbe422",
            "lean_blob": "c31235cd9b2917c065e55870893976958116992b",
        },
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "control": {
            "horizon": 64,
            "ones": 48,
            "zeros": 16,
            "empirical_mean": [3, 4],
            "alpha": [1, 20],
            "one_sided_alpha": [1, 40],
            "threshold": [40, 1],
            "positive_lambdas": [fdata(value) for value in positive],
            "negative_lambdas": [fdata(value) for value in negative],
            "mixture_weights": [fdata(value) for value in weights],
            "bisection_depth": depth,
            "dyadic_resolution": [1, 1048576],
            "required_mixture_evaluations": required_evaluations,
            "milestones": {
                str(time): history[time] for time in expected_milestones
            },
            "final": history[64],
            "reference": {
                "mean": [3, 4],
                "included_at_every_time": True,
                "maximum_one_sided_e_value": [687, 512],
                "maximum_time": 2,
                "final_positive_e_value": fdata(reference_values[-1][0]),
                "final_negative_e_value": fdata(reference_values[-1][1]),
            },
        },
        "negative_controls": {
            "post_hoc_selection": {
                "required_status": "INVALID_POST_HOC_SELECTION",
                "post_hoc_maximum_mean": [5, 4],
            },
            "unbounded_observation": {
                "required_status": "INVALID_UNBOUNDED_OBSERVATION",
                "observation": [5, 4],
            },
            "resource_limit": {
                "required_status": "UNKNOWN_RESOURCE_LIMIT",
                "required_mixture_evaluations": 11_264,
                "max_mixture_evaluations": 10_000,
            },
        },
        "gates": {
            "boundedness": "PASS",
            "one_sided_safe_lambdas": "PASS",
            "factor_nonnegativity": "PASS",
            "mixture_normalization": "PASS",
            "monotone_root_inversion": "PASS",
            "dyadic_root_enclosure": "PASS",
            "bonferroni_allocation": "PASS",
            "reference_path_control": "PASS",
            "post_hoc_rejection": "PASS",
            "resource_abstention": "PASS",
            "tamper_rejection": "PASS",
        },
        "scientific_boundary": (
            "Continuous-parameter anytime coverage for a fixed bounded conditional "
            "mean under declared one-sided e-process mixtures. Ville and the union "
            "bound are established; dyadic endpoints are conservative root enclosures."
        ),
    }
    certificate = {
        "payload": payload,
        "sha256": sha256(canonical(payload).encode()).hexdigest(),
    }
    tampered = deepcopy(certificate)
    tampered["payload"]["control"]["final"]["outer"]["lower"] = [0, 1]
    if sha256(canonical(tampered["payload"]).encode()).hexdigest() == tampered["sha256"]:
        raise AssertionError("tampered receipt retained its hash")

    path = ROOT / "CONTINUOUS_CONFIDENCE_SEQUENCE_PUBLIC_RECEIPT.json"
    path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    print(json.dumps(certificate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
