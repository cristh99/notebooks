"""Predeclare final-holdout sizes for an exact selective-risk certificate."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .risk_certificate import (
    CertificateConfig,
    SelectiveRiskCounts,
    build_certificate,
)


SCHEMA = "ocr-real-risk-sample-size-plan/2"


@dataclass(frozen=True)
class PlanningScenario:
    baseline_error_rate: float
    acceptance_rate: float
    accepted_errors: int
    counterfactual_accepts: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("baseline_error_rate", self.baseline_error_rate),
            ("acceptance_rate", self.acceptance_rate),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must lie in (0, 1]")
        if self.accepted_errors < 0 or self.counterfactual_accepts < 0:
            raise ValueError("error counts must be non-negative")


def counts_for_size(
    size: int,
    scenario: PlanningScenario,
) -> SelectiveRiskCounts:
    if size <= 0:
        raise ValueError("size must be positive")
    baseline_errors = max(
        1,
        math.floor(size * scenario.baseline_error_rate),
    )
    accepted = max(1, math.floor(size * scenario.acceptance_rate))
    if scenario.accepted_errors > accepted:
        raise ValueError("accepted_errors exceed accepted locations")
    return SelectiveRiskCounts(
        eligible_locations=size,
        baseline_errors=baseline_errors,
        accepted_locations=accepted,
        accepted_errors=scenario.accepted_errors,
        counterfactual_accepts=scenario.counterfactual_accepts,
        counterfactual_trials=accepted,
    )


def coverage_is_finitely_impossible(
    scenario: PlanningScenario,
    config: CertificateConfig,
) -> bool:
    """Prove when no finite denominator can clear the coverage lower bound.

    The planned accepted count is ``floor(n * acceptance_rate)``. Its observed
    coverage is therefore never greater than the assumed acceptance rate, and
    an exact one-sided lower confidence bound is strictly below the observed
    finite-sample proportion. If the assumed rate is at or below the required
    floor, no finite sample can pass that gate.
    """
    return scenario.acceptance_rate <= config.minimum_coverage


def minimum_size(
    scenario: PlanningScenario,
    config: CertificateConfig,
    *,
    minimum: int = 100,
    maximum: int = 100_000,
) -> dict[str, object]:
    if minimum <= 0 or maximum < minimum:
        raise ValueError("invalid search interval")
    if coverage_is_finitely_impossible(scenario, config):
        return {
            "scenario": asdict(scenario),
            "minimum_size": None,
            "searched_through": 0,
            "evaluated_sizes": 0,
            "passes": False,
            "reason": "FINITE_COVERAGE_BOUND_IMPOSSIBLE",
            "proof": (
                "floor(n*a)/n <= a <= coverage floor, while the exact "
                "one-sided lower bound is strictly below the observed "
                "finite-sample coverage"
            ),
        }

    reports: dict[int, dict[str, object]] = {}

    def evaluate(size: int) -> dict[str, object]:
        report = reports.get(size)
        if report is None:
            report = build_certificate(
                counts_for_size(size, scenario),
                config,
            )
            reports[size] = report
        return report

    # Find a passing ceiling geometrically. Monotonicity is deliberately not
    # assumed; this phase only obtains a finite exact search boundary.
    ceiling = minimum
    while True:
        if bool(evaluate(ceiling)["gates"]["pass"]):
            break
        if ceiling >= maximum:
            return {
                "scenario": asdict(scenario),
                "minimum_size": None,
                "searched_through": maximum,
                "evaluated_sizes": len(reports),
                "passes": False,
                "reason": "NO_PASS_WITHIN_SEARCH_LIMIT",
            }
        ceiling = min(maximum, max(ceiling + 1, ceiling * 2))

    # Scan from the declared minimum to the passing ceiling. This preserves the
    # exact first passing integer even when floor-rounded counts create local
    # pass/fail reversals around a boundary.
    for size in range(minimum, ceiling + 1):
        report = evaluate(size)
        if bool(report["gates"]["pass"]):
            return {
                "scenario": asdict(scenario),
                "minimum_size": size,
                "passes": True,
                "searched_through": ceiling,
                "evaluated_sizes": len(reports),
                "certificate_at_minimum": report,
            }
    raise AssertionError("passing ceiling was not found during exact scan")


def default_scenarios() -> Iterable[PlanningScenario]:
    for baseline in (0.05, 0.10, 0.15, 0.20):
        for acceptance in (0.25, 0.50, 0.75):
            for retained_errors in (0, 1, 2):
                yield PlanningScenario(
                    baseline_error_rate=baseline,
                    acceptance_rate=acceptance,
                    accepted_errors=retained_errors,
                )


def build_plan(
    config: CertificateConfig = CertificateConfig(),
) -> dict[str, object]:
    scenarios = [
        minimum_size(scenario, config)
        for scenario in default_scenarios()
    ]
    return {
        "schema": SCHEMA,
        "config": asdict(config),
        "rounding": {
            "baseline_errors": "max(1, floor(n * assumed rate))",
            "accepted_locations": "max(1, floor(n * assumed coverage))",
        },
        "search": {
            "method": (
                "finite-impossibility proof, geometric passing ceiling, "
                "then exact integer scan from declared minimum"
            ),
            "monotonicity_assumed": False,
            "first_passing_integer_preserved": True,
        },
        "scenarios": scenarios,
        "rule": (
            "The final sample size must be selected from the canary's lower "
            "confidence bound for baseline error and lower confidence bound "
            "for coverage, never from point estimates alone."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ocr_real_risk_v1/run/sample_size_plan.json"),
    )
    parser.add_argument("--minimum-coverage", type=float, default=0.25)
    args = parser.parse_args()
    report = build_plan(
        CertificateConfig(minimum_coverage=args.minimum_coverage)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
