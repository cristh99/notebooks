from __future__ import annotations

import unittest

from .benchmark import (
    MAX_PP_EFFECTIVE_CPU_PARALLELISM,
    PP_ENGINE,
    PP_ENGINE_CONFIG,
    decision_from,
    thread_evidence,
)


def synthetic_pages(cpu: float = 10.0, wall: float = 10.0) -> list[dict]:
    return [
        {
            "isolated": {
                "pp_1024": {
                    "runtime": {
                        "cpu_seconds": cpu,
                        "wall_seconds": wall,
                    }
                }
            },
            "parallel": {
                "pp_1024": {
                    "runtime": {
                        "cpu_seconds": cpu,
                        "wall_seconds": wall,
                    }
                }
            },
        }
    ]


def synthetic_report() -> dict:
    return {
        "evaluation": {
            "policy": {
                "precision": 0.99,
                "reference_coverage": 0.40,
                "prediction_count": 350,
            },
            "false_acceptance_error_reduction_factor": 12.0,
        },
        "leave_one_page_out": {"passes": 19},
        "parity": {
            "isolated_parallel_text_hashes_equal": True,
            "tesseract_vs_frozen_speed_frontier": {"f1": 0.98},
            "pp_1024_vs_frozen_speed_frontier": {"f1": 0.90},
        },
        "runtime": {
            "pair_ratio_to_tesseract": 1.05,
            "mean_extra_wall_seconds_per_page": 0.10,
            "p90_page_extra_wall_seconds": 0.25,
        },
        "thread_evidence": {
            "passes": True,
        },
    }


class StaticOneThreadTests(unittest.TestCase):
    def test_explicit_static_engine_config(self) -> None:
        self.assertEqual(PP_ENGINE, "paddle_static")
        self.assertEqual(PP_ENGINE_CONFIG["cpu_threads"], 1)
        self.assertEqual(PP_ENGINE_CONFIG["run_mode"], "mkldnn")

    def test_measured_single_thread_demand_passes(self) -> None:
        evidence = thread_evidence({"pages": synthetic_pages()})
        self.assertEqual(evidence["isolated_effective_cpu_parallelism"], 1.0)
        self.assertTrue(evidence["passes"])

    def test_hidden_oversubscription_fails_closed(self) -> None:
        evidence = thread_evidence(
            {"pages": synthetic_pages(cpu=14.0, wall=10.0)}
        )
        self.assertGreater(
            evidence["maximum_observed_effective_cpu_parallelism"],
            MAX_PP_EFFECTIVE_CPU_PARALLELISM,
        )
        self.assertFalse(evidence["passes"])

    def test_thread_gate_is_part_of_promotion(self) -> None:
        report = synthetic_report()
        report["thread_evidence"]["passes"] = False
        decision = decision_from(report)
        self.assertTrue(decision["quality_gate"])
        self.assertFalse(decision["thread_gate"])
        self.assertFalse(decision["runtime_gate"])
        self.assertFalse(decision["promotion_gate"])

    def test_all_unchanged_gates_can_pass(self) -> None:
        decision = decision_from(synthetic_report())
        self.assertTrue(decision["quality_gate"])
        self.assertTrue(decision["thread_gate"])
        self.assertTrue(decision["runtime_gate"])
        self.assertTrue(decision["promotion_gate"])


if __name__ == "__main__":
    unittest.main()
