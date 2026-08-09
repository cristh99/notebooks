from __future__ import annotations

import copy
import unittest
from fractions import Fraction

from logic_power_v10 import MonitorStatus, build_certificate, verify_certificate

from finance_power_v1.capital_allocation import (
    make_capital_allocation_scenarios,
    make_exact_capital_allocation_problem,
    make_impossible_capital_allocation_problem,
)
from finance_power_v1.domain_cases import all_domain_cases
from finance_power_v1.finite_decision import (
    EvidenceAcquisition,
    FinancialWorld,
    compile_financial_decision,
)
from finance_power_v1.run import FINANCE_POWER_SCHEMA, build_report


class FinancePowerV1Tests(unittest.TestCase):
    def test_exact_npv_decision_boundary(self) -> None:
        scenarios = {
            scenario.scenario_id: scenario
            for scenario in make_capital_allocation_scenarios()
        }
        approved = {
            scenario_id
            for scenario_id, scenario in scenarios.items()
            if scenario.approve
        }
        self.assertEqual(
            approved,
            {
                "strong__controlled__cheap",
                "strong__controlled__expensive",
                "strong__overrun__cheap",
                "strong__overrun__expensive",
                "weak__controlled__cheap",
            },
        )
        self.assertEqual(
            scenarios["weak__controlled__cheap"].npv,
            Fraction(10, 11),
        )
        self.assertEqual(
            scenarios["weak__controlled__expensive"].npv,
            Fraction(-10),
        )

    def test_capital_allocation_minimum_basis_and_policy(self) -> None:
        problem = make_exact_capital_allocation_problem()
        self.assertIsNone(problem.obstruction())

        basis = problem.exact_fixed_basis()
        self.assertIsNotNone(basis)
        self.assertEqual(
            tuple(experiment.name for experiment in basis or ()),
            ("binding_term_sheet", "pilot_and_bid"),
        )
        self.assertEqual(
            sum(
                (experiment.cost for experiment in basis or ()),
                Fraction(0),
            ),
            Fraction(5),
        )

        policy = problem.optimal_policy()
        self.assertTrue(policy["exact"])
        self.assertEqual(policy["worst_cost"], [5, 1])
        self.assertEqual(policy["expected_cost"], [21, 5])
        self.assertEqual(policy["tree"]["experiment"], "pilot_and_bid")

    def test_capital_exact_certificate_replays(self) -> None:
        certificate = build_certificate(
            make_exact_capital_allocation_problem(),
            "capital-allocation-exact",
        )
        self.assertEqual(verify_certificate(certificate), [])

    def test_capital_impossible_control_returns_obstruction(self) -> None:
        problem = make_impossible_capital_allocation_problem()
        self.assertIsNotNone(problem.obstruction())
        policy = problem.optimal_policy()
        self.assertFalse(policy["exact"])
        self.assertEqual(
            policy["tree"]["status"],
            MonitorStatus.IMPOSSIBLE.value,
        )
        certificate = build_certificate(
            problem,
            "capital-allocation-impossible",
        )
        self.assertEqual(verify_certificate(certificate), [])
        self.assertIsNotNone(
            certificate["payload"]["analysis"]["obstruction"]
        )

    def test_monitor_semantics(self) -> None:
        problem = make_exact_capital_allocation_problem()
        true_worlds = [
            hypothesis
            for hypothesis, value in problem.property_values.items()
            if value
        ]
        false_worlds = [
            hypothesis
            for hypothesis, value in problem.property_values.items()
            if not value
        ]
        self.assertEqual(problem.monitor(true_worlds), MonitorStatus.TRUE)
        self.assertEqual(problem.monitor(false_worlds), MonitorStatus.FALSE)
        self.assertEqual(
            problem.monitor(problem.hypotheses),
            MonitorStatus.UNKNOWN,
        )
        self.assertEqual(problem.monitor(()), MonitorStatus.INCONSISTENT)

    def test_generic_financial_compiler(self) -> None:
        worlds = (
            FinancialWorld(
                world_id="go",
                decision=True,
                prior=Fraction(1, 2),
                attributes={"signal": "positive"},
            ),
            FinancialWorld(
                world_id="stop",
                decision=False,
                prior=Fraction(1, 2),
                attributes={"signal": "negative"},
            ),
        )
        problem = compile_financial_decision(
            worlds,
            (
                EvidenceAcquisition(
                    name="read_signal",
                    cost=Fraction(1),
                    fields=("signal",),
                ),
            ),
        )
        self.assertIsNone(problem.obstruction())
        self.assertEqual(
            tuple(item.name for item in problem.exact_fixed_basis() or ()),
            ("read_signal",),
        )
        self.assertTrue(problem.optimal_policy()["exact"])

    def test_all_domain_exact_cases_match_verified_costs(self) -> None:
        expected = {
            "credit_underwriting": (Fraction(5), [5, 1], [7, 2]),
            "insurance_reserve": (Fraction(4), [4, 1], [7, 2]),
            "liquidity_intervention": (Fraction(3), [3, 1], [9, 4]),
            "portfolio_hedge": (Fraction(3), [3, 1], [2, 1]),
        }
        for name, (exact, _) in sorted(all_domain_cases().items()):
            with self.subTest(domain=name):
                self.assertIsNone(exact.obstruction())
                basis = exact.exact_fixed_basis()
                self.assertIsNotNone(basis)
                basis_cost = sum(
                    (item.cost for item in basis or ()),
                    Fraction(0),
                )
                expected_basis, expected_worst, expected_mean = expected[name]
                self.assertEqual(basis_cost, expected_basis)
                policy = exact.optimal_policy()
                self.assertTrue(policy["exact"])
                self.assertEqual(policy["worst_cost"], expected_worst)
                self.assertEqual(policy["expected_cost"], expected_mean)
                certificate = build_certificate(exact, f"{name}-exact")
                self.assertEqual(verify_certificate(certificate), [])

    def test_all_domain_negative_controls_are_impossible(self) -> None:
        for name, (_, impossible) in sorted(all_domain_cases().items()):
            with self.subTest(domain=name):
                self.assertIsNotNone(impossible.obstruction())
                policy = impossible.optimal_policy()
                self.assertFalse(policy["exact"])
                self.assertEqual(
                    policy["tree"]["status"],
                    MonitorStatus.IMPOSSIBLE.value,
                )
                certificate = build_certificate(
                    impossible,
                    f"{name}-impossible",
                )
                self.assertEqual(verify_certificate(certificate), [])

    def test_tampering_is_rejected(self) -> None:
        certificate = build_certificate(
            make_exact_capital_allocation_problem(),
            "capital-allocation-exact",
        )
        tampered = copy.deepcopy(certificate)
        tampered["payload"]["case"] = "altered"
        self.assertEqual(verify_certificate(tampered), ["payload-hash"])

    def test_report_is_deterministic_and_complete(self) -> None:
        first = build_report()
        second = build_report()
        self.assertEqual(first, second)
        self.assertEqual(first["payload"]["schema"], FINANCE_POWER_SCHEMA)
        self.assertEqual(
            set(first["payload"]["domains"]),
            {
                "capital_allocation",
                "credit_underwriting",
                "insurance_reserve",
                "liquidity_intervention",
                "portfolio_hedge",
            },
        )
        self.assertEqual(len(first["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
