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


SCHEMA = "ocr-real-risk-sample-size-plan/1"


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


def counts_for_size(size: int, scenario: PlanningScenario) -> SelectiveRiskCounts:
    if size <= 0:
        raise ValueError("size must be positive")
    baseline_errors = max(1, math.floor(size * scenario.baseline_error_rate))
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


def minimum_size(
    scenario: PlanningScenario,
    config: CertificateConfig,
    *,
    minimum: int = 100,
    maximum: int = 100_000,
) -> dict[str, object]:
    if minimum <= 0 or maximum < minimum:
        raise ValueError("invalid search interval")
    # Monotonicity is not assumed across rounded counts. Search in increasing
    # blocks, then identify the first passing integer in the bracket.
    first_pass: int | None = None
    for size in range(minimum, maximum + 1):
        report = build_certificate(counts_for_size(size, scenario), config)
        if report["gates"]["pass"]:
            first_pass = size
            break
    if first_pass is None:
        return {
            "scenario": asdict(scenario),
            "minimum_size": None,
            "searched_through": maximum,
            "passes": False,
        }
    report = build_certificate(counts_for_size(first_pass, scenario), config)
    return {
        "scenario": asdict(scenario),
        "minimum_size": first_pass,
        "passes": True,
        "certificate_at_minimum": report,
    }


def default_scenarios() -> Iterable[PlanningScenario]:
    for baseline in (0.05, 0.10, 0.15, 0.20):
        for acceptance in (0.25, 0.50, 0.75):
            for retained_errors in (0, 1, 2):
                yield PlanningScenario(
                    baseline_error_rate=baseline,
                    acceptance_rate=acceptance,
                    accepted_errors=retained_errors,
                )


def build_plan(config: CertificateConfig = CertificateConfig()) -> dict[str, object]:
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
