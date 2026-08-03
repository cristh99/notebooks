from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from logic_power_v10 import ActiveDiscoveryProblem, Experiment


_ALLOWED_EVIDENCE_FIELDS = frozenset(
    {"demand", "capex_state", "funding_state"}
)


@dataclass(frozen=True)
class CapitalAllocationScenario:
    """One finite state of the world for an investment decision."""

    scenario_id: str
    demand: str
    capex_state: str
    funding_state: str
    terminal_cash_flow: Fraction
    capex: Fraction
    discount_rate: Fraction
    prior: Fraction

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if self.terminal_cash_flow < 0:
            raise ValueError("terminal_cash_flow must be non-negative")
        if self.capex <= 0:
            raise ValueError("capex must be positive")
        if self.discount_rate <= -1:
            raise ValueError("discount_rate must be greater than -1")
        if self.prior <= 0:
            raise ValueError("prior must be positive")

    @property
    def npv(self) -> Fraction:
        """Exact one-period NPV, represented as a rational number."""
        return (
            self.terminal_cash_flow / (Fraction(1) + self.discount_rate)
            - self.capex
        )

    @property
    def approve(self) -> bool:
        return self.npv > 0


@dataclass(frozen=True)
class DueDiligenceTest:
    """Admissible evidence acquisition with exact rational cost."""

    name: str
    cost: Fraction
    evidence_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("test name must be non-empty")
        if self.cost <= 0:
            raise ValueError("test cost must be positive")
        if not self.evidence_fields:
            raise ValueError("at least one evidence field is required")
        unknown = set(self.evidence_fields) - _ALLOWED_EVIDENCE_FIELDS
        if unknown:
            raise ValueError(f"unsupported evidence fields: {sorted(unknown)}")
        if len(set(self.evidence_fields)) != len(self.evidence_fields):
            raise ValueError("evidence fields must be unique")

    def observe(self, scenario: CapitalAllocationScenario) -> str:
        return "|".join(
            str(getattr(scenario, field))
            for field in self.evidence_fields
        )


def compile_capital_allocation_problem(
    scenarios: Sequence[CapitalAllocationScenario],
    tests: Sequence[DueDiligenceTest],
) -> ActiveDiscoveryProblem:
    """Compile a finite financial decision into Logic Power v10."""
    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    if not scenario_ids:
        raise ValueError("at least one scenario is required")
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("scenario identifiers must be unique")

    test_names = [test.name for test in tests]
    if len(set(test_names)) != len(test_names):
        raise ValueError("test names must be unique")

    return ActiveDiscoveryProblem(
        hypotheses=tuple(scenario_ids),
        property_values={
            scenario.scenario_id: scenario.approve
            for scenario in scenarios
        },
        experiments=tuple(
            Experiment(
                name=test.name,
                cost=test.cost,
                observations={
                    scenario.scenario_id: test.observe(scenario)
                    for scenario in scenarios
                },
            )
            for test in tests
        ),
        prior={
            scenario.scenario_id: scenario.prior
            for scenario in scenarios
        },
    )


def make_capital_allocation_scenarios(
) -> tuple[CapitalAllocationScenario, ...]:
    """Eight exact scenarios for a one-period project decision.

    Strong demand makes the project acceptable in all four cost/funding
    combinations. Under weak demand, only controlled capex plus cheap funding
    remains acceptable. This creates a nontrivial adaptive evidence policy.
    """
    demand_cases = {
        "strong": (Fraction(180), Fraction(3, 20)),
        "weak": (Fraction(100), Fraction(1, 10)),
    }
    capex_cases = {
        "controlled": Fraction(90),
        "overrun": Fraction(125),
    }
    funding_cases = {
        "cheap": Fraction(1, 10),
        "expensive": Fraction(1, 4),
    }

    scenarios: list[CapitalAllocationScenario] = []
    for demand, (cash_flow, prior) in demand_cases.items():
        for capex_state, capex in capex_cases.items():
            for funding_state, rate in funding_cases.items():
                scenarios.append(
                    CapitalAllocationScenario(
                        scenario_id=(
                            f"{demand}__{capex_state}__{funding_state}"
                        ),
                        demand=demand,
                        capex_state=capex_state,
                        funding_state=funding_state,
                        terminal_cash_flow=cash_flow,
                        capex=capex,
                        discount_rate=rate,
                        prior=prior,
                    )
                )
    return tuple(scenarios)


def make_exact_capital_allocation_problem(
) -> ActiveDiscoveryProblem:
    """A decision in which admissible evidence can separate every conflict."""
    tests = (
        DueDiligenceTest(
            "binding_term_sheet",
            Fraction(1),
            ("funding_state",),
        ),
        DueDiligenceTest(
            "fixed_price_bid",
            Fraction(2),
            ("capex_state",),
        ),
        DueDiligenceTest(
            "full_diligence",
            Fraction(7),
            ("demand", "capex_state", "funding_state"),
        ),
        DueDiligenceTest(
            "market_validation",
            Fraction(3),
            ("demand",),
        ),
        DueDiligenceTest(
            "pilot_and_bid",
            Fraction(4),
            ("demand", "capex_state"),
        ),
    )
    return compile_capital_allocation_problem(
        make_capital_allocation_scenarios(), tests
    )


def make_impossible_capital_allocation_problem(
) -> ActiveDiscoveryProblem:
    """A decision whose evidence language omits demand information.

    Logic Power v10 must return an indistinguishable opposite pair rather than
    inventing confidence.
    """
    tests = (
        DueDiligenceTest(
            "binding_term_sheet",
            Fraction(1),
            ("funding_state",),
        ),
        DueDiligenceTest(
            "fixed_price_bid",
            Fraction(2),
            ("capex_state",),
        ),
    )
    return compile_capital_allocation_problem(
        make_capital_allocation_scenarios(), tests
    )
