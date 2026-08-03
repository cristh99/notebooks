from __future__ import annotations

import copy
import unittest

from finance_1000_problem_solver.solver import (
    GATE_STATUS,
    GATE_WEIGHTS,
    build_problem,
    build_report,
    route_problem,
    strict_score,
    verify_report,
)


class Finance1000PublicReplayTests(unittest.TestCase):
    def test_score_contract(self) -> None:
        self.assertEqual(sum(GATE_WEIGHTS.values()), 1000)
        self.assertEqual(strict_score(), 820)
        self.assertEqual(
            [gate for gate, status in GATE_STATUS.items() if status != "PASS"],
            ["G07", "G09"],
        )

    def test_route(self) -> None:
        route = route_problem(build_problem())
        self.assertEqual(route.selected_solver, "robust_minimax_regret")
        self.assertIn("logic_exact", route.eligible_solvers)
        self.assertIn("monte_carlo_evaluation", route.eligible_solvers)
        self.assertEqual(
            route.rejected_solvers["finite_dynamic_programming"],
            ("known_transition_model",),
        )

    def test_action(self) -> None:
        report = build_report()
        self.assertEqual(
            report["result"]["selected_action_portfolio"],
            "parallel_g07_g09_program",
        )
        self.assertEqual(report["result"]["open_points"], 180)
        self.assertEqual(report["certificate"]["payload"]["status"], "BLOCKED")

    def test_deterministic_and_valid(self) -> None:
        first = build_report()
        second = build_report()
        self.assertEqual(first, second)
        self.assertEqual(verify_report(first), [])

    def test_raw_tamper_is_rejected(self) -> None:
        report = build_report()
        altered = copy.deepcopy(report)
        altered["certificate"]["payload"]["result"]["strict_score"] = 1000
        self.assertIn("payload-hash", verify_report(altered))

    def test_rehashed_semantic_forgery_is_rejected(self) -> None:
        from finance_1000_problem_solver.solver import digest

        report = copy.deepcopy(build_report())
        report["certificate"]["payload"]["result"]["strict_score"] = 1000
        report["certificate"]["payload_sha256"] = digest(report["certificate"]["payload"])
        unsigned = {key: report[key] for key in report if key != "report_sha256"}
        report["report_sha256"] = digest(unsigned)
        self.assertIn("strict-score", verify_report(report))


if __name__ == "__main__":
    unittest.main()
