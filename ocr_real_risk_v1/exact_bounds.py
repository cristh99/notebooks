"""Numerically stable exact one-sided binomial confidence bounds.

The previous recurrence started at P(X=0), which underflows for large n and
moderate p.  That can turn a near-zero coverage lower bound into a large value.
This module evaluates the binomial CDF through the regularized incomplete beta
function and then inverts it by deterministic bisection.
"""
from __future__ import annotations

import math
from functools import lru_cache

_MAX_ITERATIONS = 240
_EPSILON = 3.0e-14
_FPMIN = 1.0e-300


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    result = d
    for iteration in range(1, _MAX_ITERATIONS + 1):
        doubled = 2 * iteration
        coefficient = (
            iteration * (b - iteration) * x
            / ((qam + doubled) * (a + doubled))
        )
        d = 1.0 + coefficient * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + coefficient / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        result *= d * c

        coefficient = -(
            (a + iteration) * (qab + iteration) * x
            / ((a + doubled) * (qap + doubled))
        )
        d = 1.0 + coefficient * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + coefficient / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) <= _EPSILON:
            return result
    raise ArithmeticError("incomplete-beta continued fraction did not converge")


def regularized_beta(x: float, a: float, b: float) -> float:
    if a <= 0.0 or b <= 0.0:
        raise ValueError("beta parameters must be positive")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(log_front) if log_front > math.log(_FPMIN) else 0.0
    if x < (a + 1.0) / (a + b + 2.0):
        value = front * _beta_continued_fraction(a, b, x) / a
    else:
        value = 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b
    return min(1.0, max(0.0, value))


def binomial_cdf(k: int, n: int, p: float) -> float:
    if n < 0:
        raise ValueError("n must be non-negative")
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    return regularized_beta(1.0 - p, float(n - k), float(k + 1))


@lru_cache(maxsize=131_072)
def clopper_pearson_upper(k: int, n: int, alpha: float = 0.025) -> float:
    if n <= 0 or k < 0 or k > n:
        raise ValueError("invalid binomial counts")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie in (0, 1)")
    if k == n:
        return 1.0
    if k == 0:
        return 1.0 - alpha ** (1.0 / n)
    low, high = 0.0, 1.0
    for _ in range(72):
        midpoint = (low + high) / 2.0
        if binomial_cdf(k, n, midpoint) > alpha:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2.0


@lru_cache(maxsize=131_072)
def clopper_pearson_lower(k: int, n: int, alpha: float = 0.025) -> float:
    if n <= 0 or k < 0 or k > n:
        raise ValueError("invalid binomial counts")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie in (0, 1)")
    if k == 0:
        return 0.0
    if k == n:
        return alpha ** (1.0 / n)
    return 1.0 - clopper_pearson_upper(n - k, n, alpha)
