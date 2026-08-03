from __future__ import annotations

from fractions import Fraction
from typing import Mapping

from lower_bound_compiler import (
    FiniteEstimationProblem,
    canonical_json,
    digest_payload,
    fraction_data,
    squared_distance,
)
from packing_lower_bound import FiniteClassificationProblem


def log_interval_unit(value: Fraction, terms: int) -> tuple[Fraction, Fraction]:
    if terms <= 0:
        raise ValueError("terms must be positive")
    if not (1 <= value <= 2):
        raise ValueError("unit log interval requires value in [1,2]")
    if value == 1:
        return Fraction(0), Fraction(0)
    z = (value - 1) / (value + 1)
    partial = sum(
        (
            z ** (2 * index + 1) / Fraction(2 * index + 1)
            for index in range(terms)
        ),
        Fraction(0),
    )
    lower = 2 * partial
    remainder = (
        2
        * z ** (2 * terms + 1)
        / (Fraction(2 * terms + 1) * (1 - z * z))
    )
    return lower, lower + remainder


def log_interval(value: Fraction, terms: int = 16) -> tuple[Fraction, Fraction]:
    if value <= 0:
        raise ValueError("log requires a positive rational")
    if value == 1:
        return Fraction(0), Fraction(0)
    if value < 1:
        lower, upper = log_interval(1 / value, terms)
        return -upper, -lower

    exponent = 0
    reduced = value
    while reduced > 2:
        reduced /= 2
        exponent += 1
    if reduced == 2:
        reduced = Fraction(1)
        exponent += 1

    log2_lower, log2_upper = log_interval_unit(Fraction(2), terms)
    reduced_lower, reduced_upper = log_interval_unit(reduced, terms)
    return (
        exponent * log2_lower + reduced_lower,
        exponent * log2_upper + reduced_upper,
    )


def decimal_string(value: Fraction, digits: int = 18) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    scale = 10**digits
    quotient, remainder = divmod(value.numerator * scale, value.denominator)
    if 2 * remainder >= value.denominator:
        quotient += 1
    whole, fractional = divmod(quotient, scale)
    return f"{sign}{whole}.{fractional:0{digits}d}"


def uniform_mixture(problem: FiniteClassificationProblem) -> tuple[Fraction, ...]:
    weight = Fraction(1, len(problem.worlds))
    return tuple(
        sum(
            (
                weight * problem.laws[world][outcome_index]
                for world in problem.worlds
            ),
            Fraction(0),
        )
        for outcome_index in range(len(problem.outcomes))
    )


def uniform_mutual_information_interval(
    problem: FiniteClassificationProblem,
    *,
    log_terms: int = 16,
) -> dict[str, object]:
    mixture = uniform_mixture(problem)
    prior = Fraction(1, len(problem.worlds))
    lower = Fraction(0)
    upper = Fraction(0)
    nonzero_terms = 0
    maximum_log_width = Fraction(0)
    for world in problem.worlds:
        for outcome_index, probability in enumerate(problem.laws[world]):
            if probability == 0:
                continue
            ratio = probability / mixture[outcome_index]
            log_lower, log_upper = log_interval(ratio, log_terms)
            coefficient = prior * probability
            lower += coefficient * log_lower
            upper += coefficient * log_upper
            nonzero_terms += 1
            maximum_log_width = max(
                maximum_log_width, log_upper - log_lower
            )
    if lower < 0:
        lower = Fraction(0)
    return {
        "uniform_prior": fraction_data(prior),
        "mixture": [fraction_data(value) for value in mixture],
        "lower": fraction_data(lower),
        "upper": fraction_data(upper),
        "lower_decimal": decimal_string(lower),
        "upper_decimal": decimal_string(upper),
        "nonzero_terms": nonzero_terms,
        "log_terms": log_terms,
        "maximum_log_interval_width": fraction_data(maximum_log_width),
    }


def certified_fano_bound(
    problem: FiniteClassificationProblem,
    *,
    log_terms: int = 16,
) -> dict[str, object]:
    classes = len(problem.worlds)
    if classes < 3:
        raise ValueError("Fano compiler requires at least three classes")
    information = uniform_mutual_information_interval(
        problem, log_terms=log_terms
    )
    information_upper = Fraction(*information["upper"])
    _, log2_upper = log_interval(Fraction(2), log_terms)
    logm_lower, logm_upper = log_interval(Fraction(classes), log_terms)
    if logm_lower <= 0:
        raise AssertionError("log class count must be positive")
    ratio_upper = (information_upper + log2_upper) / logm_lower
    lower_bound = max(Fraction(0), 1 - ratio_upper)
    return {
        "method": "certified finite Fano inequality",
        "classes": classes,
        "mutual_information_interval": information,
        "log_two_interval": {
            "lower": fraction_data(log_interval(Fraction(2), log_terms)[0]),
            "upper": fraction_data(log2_upper),
        },
        "log_class_count_interval": {
            "lower": fraction_data(logm_lower),
            "upper": fraction_data(logm_upper),
        },
        "classification_lower_bound": fraction_data(lower_bound),
        "classification_lower_decimal": decimal_string(lower_bound),
        "certificate_logic": (
            "I<=I_upper, log(2)<=L2_upper and log(M)>=LM_lower; "
            "therefore Pe>=1-(I_upper+L2_upper)/LM_lower."
        ),
    }


def build_fano_certificate(
    problem: FiniteClassificationProblem,
    case_name: str,
    *,
    log_terms: int = 16,
) -> dict[str, object]:
    payload = {
        "schema": "inference-power-compiler/fano-certificate/1",
        "case": case_name,
        "problem": problem.to_data(),
        "log_terms": log_terms,
        "result": certified_fano_bound(problem, log_terms=log_terms),
    }
    return {"payload": payload, "sha256": digest_payload(payload)}


def verify_fano_certificate(
    certificate: Mapping[str, object],
) -> list[str]:
    payload = certificate.get("payload")
    payload_hash = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(payload_hash, str):
        return ["certificate-shape"]
    if digest_payload(payload) != payload_hash:
        return ["payload-hash"]
    try:
        problem_data = payload.get("problem")
        case_name = payload.get("case")
        log_terms = payload.get("log_terms")
        if (
            not isinstance(problem_data, Mapping)
            or not isinstance(case_name, str)
            or not isinstance(log_terms, int)
        ):
            raise ValueError("malformed Fano payload")
        problem = FiniteClassificationProblem.from_data(problem_data)
        rebuilt = build_fano_certificate(
            problem, case_name, log_terms=log_terms
        )
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    return [] if canonical_json(rebuilt["payload"]) == canonical_json(payload) else ["semantic-replay"]


def fano_packing_bound(
    estimation: FiniteEstimationProblem,
    *,
    log_terms: int = 16,
) -> dict[str, object]:
    classification = FiniteClassificationProblem(
        estimation.worlds, estimation.outcomes, estimation.laws
    )
    fano = certified_fano_bound(classification, log_terms=log_terms)
    separation_sq = min(
        squared_distance(
            estimation.targets[left], estimation.targets[right]
        )
        for left_index, left in enumerate(estimation.worlds)
        for right in estimation.worlds[left_index + 1 :]
    )
    testing_lower = Fraction(*fano["classification_lower_bound"])
    estimation_lower = separation_sq * testing_lower / 4
    return {
        "minimum_squared_target_separation": fraction_data(separation_sq),
        "packing_radius_squared": fraction_data(separation_sq / 4),
        "classification_fano_lower_bound": fraction_data(testing_lower),
        "estimation_lower_bound": fraction_data(estimation_lower),
        "estimation_lower_decimal": decimal_string(estimation_lower),
        "fano": fano,
    }
