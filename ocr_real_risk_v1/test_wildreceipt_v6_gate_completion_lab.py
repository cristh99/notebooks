from __future__ import annotations

import unittest

from .wildreceipt_v6_gate_completion_lab import (
    DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST,
    DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN,
    GATE_POLICY,
    predict_v6_gate_completion,
)


def row(
    *,
    detector: str = "1234",
    forest: str = "1234",
    gray: str = "1234",
    autocontrast: str = "1234",
    confidence: float = 90.0,
    conflict: bool = False,
) -> dict:
    return {
        "candidate": {
            "eligible": True,
            "claim": detector,
            "prediction": forest,
            "matched": {
                "confidence": confidence,
                "equal_length_conflicts": ["9999"] if conflict else [],
            },
            "guard": {
                "readings": {
                    "gray": {"digits": gray},
                    "autocontrast": {"digits": autocontrast},
                }
            },
        }
    }


class WildReceiptV6GateCompletionLabTests(unittest.TestCase):
    def test_base_anchor_remains_available(self) -> None:
        self.assertEqual(predict_v6_gate_completion(row()), "1234")
        self.assertIsNone(
            predict_v6_gate_completion(
                row(forest="1294", gray="", autocontrast="")
            )
        )

    def test_high_detector_guard_threshold_is_strict(self) -> None:
        below = row(
            forest="1294",
            confidence=DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN,
        )
        above = row(
            forest="1294",
            confidence=(
                DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN + 0.01
            ),
        )
        self.assertIsNone(predict_v6_gate_completion(below))
        self.assertEqual(predict_v6_gate_completion(above), "1234")

    def test_high_detector_forest_gray_branch(self) -> None:
        below = row(
            autocontrast="1294",
            confidence=DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST - 0.01,
            conflict=True,
        )
        at = row(
            autocontrast="1294",
            confidence=DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST,
            conflict=True,
        )
        self.assertIsNone(predict_v6_gate_completion(below))
        self.assertEqual(predict_v6_gate_completion(at), "1234")

    def test_conflicting_branch_outputs_abstain(self) -> None:
        example = row(
            detector="1234",
            forest="1294",
            gray="1234",
            autocontrast="1234",
            confidence=95.0,
        )
        self.assertEqual(predict_v6_gate_completion(example), "1234")
        self.assertEqual(
            GATE_POLICY.counterfactual_semantics,
            "final_output_collision_proxy",
        )

    def test_non_digit_and_length_mismatch_fail_closed(self) -> None:
        self.assertIsNone(
            predict_v6_gate_completion(row(detector="12A4"))
        )
        self.assertIsNone(
            predict_v6_gate_completion(
                row(forest="12345", gray="", autocontrast="")
            )
        )


if __name__ == "__main__":
    unittest.main()
