from __future__ import annotations

import unittest

from .benchmark import (
    MAX_PP_EFFECTIVE_CPU_PARALLELISM,
    affinity_evidence,
    evaluate_pages,
    output_parity,
    percentile,
    runtime_metrics,
    stable_payload,
    thread_evidence,
)


def runtime_payload(wall: float, cpu: float, affinity: list[int], digest: str) -> dict:
    return {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "effective_cpu_parallelism": cpu / wall,
        "parent_affinity": affinity,
        "affinity": affinity,
        "prediction_sha256": digest,
    }


def synthetic_page() -> dict:
    all_core = {"text": "", "runtime": runtime_payload(3.0, 8.0, [0, 1, 2, 3], "t")}
    reserved = {"text": "", "runtime": runtime_payload(3.1, 8.0, [0, 1, 2], "t")}
    isolated_pp = {
        "text": "",
        "runtime": runtime_payload(3.0, 3.0, [3], "p"),
    }
    parallel = {
        "pair_wall_seconds": 3.2,
        "tesseract": {
            "text": "",
            "runtime": runtime_payload(3.1, 8.0, [0, 1, 2], "t"),
        },
        "pp_1024": {
            "text": "",
            "runtime": runtime_payload(3.1, 3.1, [3], "p"),
        },
    }
    return {
        "page_id": "p1",
        "reference_tokens": ["1", "1", "2", "2"],
        "tesseract_tokens": ["1", "1", "2", "2", "9", "9"],
        "pp_1024_tokens": ["1", "1", "2", "2"],
        "accepted_tokens": ["1", "1", "2", "2"],
        "controls": {
            "all_core_tesseract": all_core,
            "reserved_tesseract": reserved,
            "isolated_pp": isolated_pp,
        },
        "parallel": parallel,
    }


class ProcessIsolatedBenchmarkTests(unittest.TestCase):
    def test_quality_uses_independent_repeated_intersection(self) -> None:
        result = evaluate_pages([synthetic_page()])
        self.assertEqual(result["policy"]["precision"], 1.0)
        self.assertEqual(result["policy"]["prediction_count"], 4)

    def test_runtime_is_charged_against_all_core_control(self) -> None:
        metrics = runtime_metrics([synthetic_page()])
        self.assertAlmostEqual(metrics["pair_ratio_to_all_core_tesseract"], 3.2 / 3.0)
        self.assertAlmostEqual(metrics["mean_extra_wall_seconds_per_page"], 0.2)
        self.assertAlmostEqual(metrics["reservation_slowdown_ratio"], 3.1 / 3.0)

    def test_affinity_gate_requires_disjoint_complete_partition(self) -> None:
        pages = [synthetic_page()]
        result = affinity_evidence(
            pages,
            [0, 1, 2, 3],
            [0, 1, 2],
            3,
            {"affinity": [3]},
        )
        self.assertTrue(result["disjoint"])
        self.assertTrue(result["union_complete"])
        self.assertTrue(result["passes"])

    def test_affinity_overlap_fails_closed(self) -> None:
        result = affinity_evidence(
            [synthetic_page()],
            [0, 1, 2, 3],
            [0, 1, 2, 3],
            3,
            {"affinity": [3]},
        )
        self.assertFalse(result["disjoint"])
        self.assertFalse(result["passes"])

    def test_physical_thread_gate_passes_one_cpu(self) -> None:
        evidence = thread_evidence([synthetic_page()])
        self.assertLessEqual(
            evidence["maximum_observed_effective_cpu_parallelism"],
            MAX_PP_EFFECTIVE_CPU_PARALLELISM,
        )
        self.assertTrue(evidence["passes"])

    def test_hidden_parallelism_fails_thread_gate(self) -> None:
        page = synthetic_page()
        page["parallel"]["pp_1024"]["runtime"]["cpu_seconds"] = 5.0
        page["parallel"]["pp_1024"]["runtime"]["wall_seconds"] = 3.0
        evidence = thread_evidence([page])
        self.assertFalse(evidence["passes"])

    def test_output_change_under_concurrency_fails_closed(self) -> None:
        page = synthetic_page()
        page["parallel"]["pp_1024"]["runtime"]["prediction_sha256"] = "changed"
        self.assertFalse(output_parity([page])["passes"])

    def test_percentile_uses_nearest_rank(self) -> None:
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.90), 4.0)
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.50), 2.0)

    def test_stable_payload_excludes_environment_and_digest(self) -> None:
        report = {
            "schema": "x",
            "value": 7,
            "environment": {"host": "runner"},
            "stable_payload_sha256": "bad",
        }
        self.assertEqual(stable_payload(report), {"schema": "x", "value": 7})


if __name__ == "__main__":
    unittest.main()
