from __future__ import annotations

import copy
import unittest

from .benchmark_cli import bind_preflight


class BenchmarkBindingTests(unittest.TestCase):
    def _benchmark(self) -> dict[str, object]:
        return {
            "payload": {
                "source": {},
                "python_gate_checks": {"performance_gate": True},
                "performance_candidate_pass": True,
                "status": "CANDIDATE_PASS_PENDING_INDEPENDENT_MODEL_REPLAY",
                "absolute_score": {"before": 423, "after": 423, "delta": 0},
            },
            "payload_canonical": "",
            "sha256": "",
        }

    def _preflight(self, status: str = "PASS_PREFLIGHT") -> dict[str, object]:
        return {
            "payload": {
                "status": status,
                "entity_overlap_counts": {
                    "train_validation": 0,
                    "train_test": 0,
                    "validation_test": 0,
                },
                "gate_checks": {
                    "zero_entity_overlap": status == "PASS_PREFLIGHT",
                    "strict_temporal_order": True,
                },
            },
            "sha256": "preflight-hash",
        }

    def _entity(self, status: str = "PASS_ENTITY_SPLIT") -> dict[str, object]:
        return {
            "payload": {
                "status": status,
                "protocol": {"seed": "seed-v1"},
                "gate_checks": {
                    "source_panel_hash_exact": True,
                    "train_positive_entities_at_least_30": True,
                    "validation_positive_entities_at_least_10": True,
                    "test_positive_entities_at_least_50": True,
                    "validation_positive_rows_at_least_20": True,
                    "test_positive_rows_at_least_100": True,
                },
            },
            "sha256": "entity-hash",
        }

    def test_binding_adds_non_compensable_entity_gates(self) -> None:
        result = bind_preflight(
            copy.deepcopy(self._benchmark()),
            self._preflight(),
            self._entity(),
        )
        payload = result["payload"]
        self.assertEqual(
            payload["source"]["preflight_report_sha256"], "preflight-hash"
        )
        self.assertEqual(
            payload["source"]["entity_split_report_sha256"], "entity-hash"
        )
        self.assertTrue(payload["python_gate_checks"]["zero_entity_overlap"])
        self.assertTrue(payload["performance_candidate_pass"])
        self.assertEqual(payload["absolute_score"]["after"], 423)

    def test_blocked_preflight_never_opens_benchmark(self) -> None:
        with self.assertRaisesRegex(ValueError, "PASS_PREFLIGHT"):
            bind_preflight(
                copy.deepcopy(self._benchmark()),
                self._preflight("BLOCKED_BEFORE_SEALED_TEST"),
                self._entity(),
            )


if __name__ == "__main__":
    unittest.main()
