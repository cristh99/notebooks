"""Exact certificate for the semantic-flagged numeric OCR risk unit.

The global OCR token stream dilutes rare but consequential numeric errors with
many easy tokens. V4 therefore defines a separate, outcome-blind risk unit: one
numeric token selected by the frozen semantic contradiction trigger before
annotations are opened. This module gives simultaneous one-sided
Clopper-Pearson bounds for baseline risk and retained accepted risk.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass

from scipy.stats import beta


@dataclass(frozen=True, slots=True)
class SelectiveRiskCertificate:
    flagged_claims: int
    baseline_errors: int
    accepted_claims: int
    final_errors: int
    quarantined_claims: int
    family_alpha: float
    alpha_per_leg: float
    baseline_risk_lower: float
    final_risk_upper: float
    certified_reduction_lower: float | None
    target_reduction: float
    pass_10x: bool
    certificate_sha256: str


def _validate_count(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def clopper_pearson_lower(errors: int, total: int, alpha: float) -> float:
    errors = _validate_count(errors, "errors")
    total = _validate_count(total, "total")
    if errors > total:
        raise ValueError("errors cannot exceed total")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be within (0, 1)")
    if total == 0 or errors == 0:
        return 0.0
    return float(beta.ppf(alpha, errors, total - errors + 1))


def clopper_pearson_upper(errors: int, total: int, alpha: float) -> float:
    errors = _validate_count(errors, "errors")
    total = _validate_count(total, "total")
    if errors > total:
        raise ValueError("errors cannot exceed total")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be within (0, 1)")
    if total == 0 or errors == total:
        return 1.0
    return float(beta.ppf(1.0 - alpha, errors + 1, total - errors))


def build_certificate(
    *,
    flagged_claims: int,
    baseline_errors: int,
    accepted_claims: int,
    final_errors: int,
    family_alpha: float = 0.05,
    target_reduction: float = 10.0,
) -> SelectiveRiskCertificate:
    """Build a simultaneous 95% selective-risk reduction certificate.

    Two one-sided confidence legs share ``family_alpha`` by Bonferroni:
    baseline error risk receives a lower bound and final accepted error risk an
    upper bound. Quarantined claims count against coverage but not accepted risk.
    """

    flagged_claims = _validate_count(flagged_claims, "flagged_claims")
    baseline_errors = _validate_count(baseline_errors, "baseline_errors")
    accepted_claims = _validate_count(accepted_claims, "accepted_claims")
    final_errors = _validate_count(final_errors, "final_errors")
    if baseline_errors > flagged_claims:
        raise ValueError("baseline_errors cannot exceed flagged_claims")
    if accepted_claims > flagged_claims:
        raise ValueError("accepted_claims cannot exceed flagged_claims")
    if final_errors > accepted_claims:
        raise ValueError("final_errors cannot exceed accepted_claims")
    if not math.isfinite(family_alpha) or not 0.0 < family_alpha < 1.0:
        raise ValueError("family_alpha must be finite and within (0, 1)")
    if not math.isfinite(target_reduction) or target_reduction <= 1.0:
        raise ValueError("target_reduction must be finite and greater than one")

    alpha_per_leg = family_alpha / 2.0
    baseline_lower = clopper_pearson_lower(
        baseline_errors, flagged_claims, alpha_per_leg
    )
    final_upper = clopper_pearson_upper(
        final_errors, accepted_claims, alpha_per_leg
    )
    reduction = baseline_lower / final_upper if final_upper > 0.0 else None
    pass_10x = bool(
        reduction is not None
        and reduction >= target_reduction
        and accepted_claims > 0
    )
    payload = {
        "schema": "ocr-selective-risk-certificate-v4/1",
        "flagged_claims": flagged_claims,
        "baseline_errors": baseline_errors,
        "accepted_claims": accepted_claims,
        "final_errors": final_errors,
        "quarantined_claims": flagged_claims - accepted_claims,
        "family_alpha": family_alpha,
        "alpha_per_leg": alpha_per_leg,
        "baseline_risk_lower": baseline_lower,
        "final_risk_upper": final_upper,
        "certified_reduction_lower": reduction,
        "target_reduction": target_reduction,
        "pass_10x": pass_10x,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()
    return SelectiveRiskCertificate(
        flagged_claims=flagged_claims,
        baseline_errors=baseline_errors,
        accepted_claims=accepted_claims,
        final_errors=final_errors,
        quarantined_claims=flagged_claims - accepted_claims,
        family_alpha=family_alpha,
        alpha_per_leg=alpha_per_leg,
        baseline_risk_lower=baseline_lower,
        final_risk_upper=final_upper,
        certified_reduction_lower=reduction,
        target_reduction=target_reduction,
        pass_10x=pass_10x,
        certificate_sha256=digest,
    )


def minimum_zero_residual_flags(
    *,
    baseline_error_fraction: float,
    accepted_fraction: float = 1.0,
    target_reduction: float = 10.0,
    family_alpha: float = 0.05,
    maximum_flags: int = 1_000_000,
) -> int:
    """Return the first flag count able to certify target reduction.

    Planned baseline errors and accepted claims are conservatively floored. A
    returned sample size is therefore sufficient at or above the declared
    baseline-error and acceptance fractions when the accepted stream contains
    zero observed residual errors. Quarantined flags remain in the baseline
    denominator but not in the retained-risk denominator.
    """

    if not math.isfinite(baseline_error_fraction) or not (
        0.0 < baseline_error_fraction <= 1.0
    ):
        raise ValueError("baseline_error_fraction must be within (0, 1]")
    if not math.isfinite(accepted_fraction) or not (0.0 < accepted_fraction <= 1.0):
        raise ValueError("accepted_fraction must be within (0, 1]")
    maximum_flags = _validate_count(maximum_flags, "maximum_flags")
    if maximum_flags < 1:
        raise ValueError("maximum_flags must be positive")
    for total in range(1, maximum_flags + 1):
        baseline_errors = math.floor(total * baseline_error_fraction)
        accepted_claims = math.floor(total * accepted_fraction)
        if baseline_errors == 0 or accepted_claims == 0:
            continue
        certificate = build_certificate(
            flagged_claims=total,
            baseline_errors=baseline_errors,
            accepted_claims=accepted_claims,
            final_errors=0,
            family_alpha=family_alpha,
            target_reduction=target_reduction,
        )
        if certificate.pass_10x:
            return total
    raise RuntimeError("maximum_flags is insufficient for the requested plan")


def to_data(certificate: SelectiveRiskCertificate) -> dict[str, object]:
    return asdict(certificate)
