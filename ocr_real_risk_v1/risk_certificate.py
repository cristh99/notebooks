"""Exact finite-sample certificate for selective numeric OCR.

The certifier separates three quantities:

* baseline error risk: wrong first-pass OCR claims / eligible locations;
* retained error risk: wrong claims among verifier ACCEPT decisions;
* selective coverage: verifier ACCEPT decisions / eligible locations.

A tenfold claim is issued only when a simultaneous one-sided confidence bound
proves baseline_risk / retained_risk >= 10 while coverage clears a predeclared
floor. This prevents an almost-always-abstaining policy from looking strong.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper


SCHEMA = "ocr-real-risk-certificate/1"
DEFAULT_ALPHA = 0.05
DEFAULT_TARGET_REDUCTION = 10.0
DEFAULT_MIN_COVERAGE = 0.25


@dataclass(frozen=True)
class BinomialObservation:
    events: int
    trials: int

    def __post_init__(self) -> None:
        if self.trials < 0:
            raise ValueError("trials must be non-negative")
        if self.events < 0 or self.events > self.trials:
            raise ValueError("events must satisfy 0 <= events <= trials")

    @property
    def rate(self) -> float:
        return self.events / self.trials if self.trials else 0.0


@dataclass(frozen=True)
class SelectiveRiskCounts:
    eligible_locations: int
    baseline_errors: int
    accepted_locations: int
    accepted_errors: int
    counterfactual_accepts: int = 0
    counterfactual_trials: int = 0

    def __post_init__(self) -> None:
        BinomialObservation(self.baseline_errors, self.eligible_locations)
        BinomialObservation(self.accepted_locations, self.eligible_locations)
        BinomialObservation(self.accepted_errors, self.accepted_locations)
        BinomialObservation(
            self.counterfactual_accepts,
            self.counterfactual_trials,
        )


@dataclass(frozen=True)
class CertificateConfig:
    alpha: float = DEFAULT_ALPHA
    target_reduction: float = DEFAULT_TARGET_REDUCTION
    minimum_coverage: float = DEFAULT_MIN_COVERAGE
    require_counterfactual_gate: bool = True
    maximum_counterfactual_accept_risk: float = 0.01

    def __post_init__(self) -> None:
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha must lie in (0, 1)")
        if self.target_reduction <= 1.0:
            raise ValueError("target_reduction must exceed 1")
        if not 0.0 <= self.minimum_coverage <= 1.0:
            raise ValueError("minimum_coverage must lie in [0, 1]")
        if not 0.0 <= self.maximum_counterfactual_accept_risk <= 1.0:
            raise ValueError(
                "maximum_counterfactual_accept_risk must lie in [0, 1]"
            )


def _alpha_legs(
    config: CertificateConfig,
    counts: SelectiveRiskCounts,
) -> int:
    del counts
    # Baseline lower risk, retained upper risk and coverage lower bound are
    # always simultaneous. Counterfactual risk is a fourth leg when required.
    return 4 if config.require_counterfactual_gate else 3


def build_certificate(
    counts: SelectiveRiskCounts,
    config: CertificateConfig = CertificateConfig(),
) -> dict[str, Any]:
    legs = _alpha_legs(config, counts)
    leg_alpha = config.alpha / legs

    baseline = BinomialObservation(
        counts.baseline_errors,
        counts.eligible_locations,
    )
    retained = BinomialObservation(
        counts.accepted_errors,
        counts.accepted_locations,
    )
    coverage = BinomialObservation(
        counts.accepted_locations,
        counts.eligible_locations,
    )
    counterfactual = BinomialObservation(
        counts.counterfactual_accepts,
        counts.counterfactual_trials,
    )

    baseline_lower = clopper_pearson_lower(
        baseline.events,
        baseline.trials,
        leg_alpha,
    )
    retained_upper = clopper_pearson_upper(
        retained.events,
        retained.trials,
        leg_alpha,
    )
    coverage_lower = clopper_pearson_lower(
        coverage.events,
        coverage.trials,
        leg_alpha,
    )
    counterfactual_upper = clopper_pearson_upper(
        counterfactual.events,
        counterfactual.trials,
        leg_alpha,
    )

    if retained_upper <= 0.0:
        reduction_lower = float("inf") if baseline_lower > 0.0 else 0.0
    else:
        reduction_lower = baseline_lower / retained_upper

    enough_denominators = bool(
        counts.eligible_locations > 0
        and counts.accepted_locations > 0
        and (
            not config.require_counterfactual_gate
            or counts.counterfactual_trials > 0
        )
    )
    risk_gate = reduction_lower >= config.target_reduction
    coverage_gate = coverage_lower >= config.minimum_coverage
    counterfactual_gate = bool(
        not config.require_counterfactual_gate
        or counterfactual_upper
        <= config.maximum_counterfactual_accept_risk
    )
    pass_gate = bool(
        enough_denominators
        and risk_gate
        and coverage_gate
        and counterfactual_gate
    )

    return {
        "schema": SCHEMA,
        "config": asdict(config),
        "counts": asdict(counts),
        "multiplicity_control": {
            "method": (
                "Bonferroni simultaneous one-sided Clopper-Pearson bounds"
            ),
            "family_alpha": config.alpha,
            "legs": legs,
            "alpha_per_leg": leg_alpha,
        },
        "observed": {
            "baseline_error_rate": baseline.rate,
            "retained_error_rate": retained.rate,
            "coverage": coverage.rate,
            "counterfactual_accept_rate": counterfactual.rate,
        },
        "simultaneous_bounds": {
            "baseline_error_lower": baseline_lower,
            "retained_error_upper": retained_upper,
            "coverage_lower": coverage_lower,
            "counterfactual_accept_upper": counterfactual_upper,
            "risk_reduction_lower": reduction_lower,
        },
        "gates": {
            "enough_denominators": enough_denominators,
            "risk_reduction_at_least_target": risk_gate,
            "coverage_at_least_floor": coverage_gate,
            "counterfactual_accept_risk_below_ceiling": counterfactual_gate,
            "pass": pass_gate,
        },
        "verdict": (
            "PASS_CERTIFIED_SELECTIVE_NUMERIC_RISK_REDUCTION"
            if pass_gate
            else "NOT_CERTIFIED"
        ),
        "interpretation": (
            "The claim concerns error among accepted numeric OCR outputs; "
            "it does not claim complete numeric coverage or full-text OCR quality."
        ),
    }
