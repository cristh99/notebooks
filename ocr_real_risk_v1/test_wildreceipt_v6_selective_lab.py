from __future__ import annotations

import unittest

from .wildreceipt_v6_selective_lab import (
    MINIMUM_ACCEPTED,
    MINIMUM_COVERAGE_LOWER,
    MINIMUM_SELECTED,
    POLICY_BY_NAME,
    TARGET_REDUCTION,
    channels,
    counterfactual_false,
    exact_summary,
    predict_crop_unanimous,
    predict_detector_forest_no_conflict,
    predict_detector_forest_or_crop_unanimous,
)


def row(
    *,
    key: str = "train-00000-of-00002:1",
    truth: str = "1234",
    detector: str = "1234",
    forest: str = "1234",
    gray: str = "1234",
    autocontrast: str = "1234",
    conflict: bool = False,
    baseline_claim: str = "1234",
    stored_counterfactual: bool = False,
    counterfactual: str = "1235",
) -> dict:
    return {
        "key": key,
        "truth": truth,
        "counterfactual_claim": counterfactual,
        "counterfactual": {"false_accept": stored_counterfactual},
        "baseline": {
            "eligible": True,
            "claim": baseline_claim,
        },
        "candidate": {
            "eligible": True,
            "claim": detector,
            "prediction": forest,
            "minimum_mean_probability": 0.4,
            "accepted": detector == forest and detector in {gray, autocontrast},
            "guard": {
                "readings": {
                    "gray": {"digits": gray},
                    "autocontrast": {"digits": autocontrast},
                }
            },
            "matched": {
                "equal_length_conflicts": ["9999"] if conflict else [],
            },
        },
    }


class WildReceiptV6SelectiveLabTests(unittest.TestCase):
    def test_channels_keep_only_equal_length_digits(self) -> None:
        observed = channels(
            row(forest="12345", gray="1234", autocontrast="")
        )
        self.assertEqual(observed, {"detector": "1234", "gray": "1234"})

    def test_detector_forest_anchor_is_fail_closed(self) -> None:
        self.assertEqual(predict_detector_forest_no_conflict(row()), "1234")
        self.assertIsNone(
            predict_detector_forest_no_conflict(row(conflict=True))
        )
        self.assertIsNone(
            predict_detector_forest_no_conflict(row(forest="1235"))
        )

    def test_crop_unanimity_can_correct_detector(self) -> None:
        example = row(
            truth="1234",
            detector="1284",
            forest="1234",
            gray="1234",
            autocontrast="1234",
        )
        self.assertEqual(predict_crop_unanimous(example), "1234")
        self.assertEqual(
            predict_detector_forest_or_crop_unanimous(example), "1234"
        )

    def test_v5_uses_stored_counterfactual_replay(self) -> None:
        example = row(stored_counterfactual=True)
        policy = POLICY_BY_NAME["v5_current"]
        prediction = policy.predictor(example)
        self.assertTrue(counterfactual_false(example, prediction, policy))

    def test_successor_uses_final_output_collision_proxy(self) -> None:
        example = row(
            detector="1235",
            forest="1235",
            gray="1235",
            autocontrast="1235",
            counterfactual="1235",
        )
        policy = POLICY_BY_NAME[
            "detector_forest_no_equal_length_conflict"
        ]
        prediction = policy.predictor(example)
        self.assertEqual(prediction, "1235")
        self.assertTrue(counterfactual_false(example, prediction, policy))

    def test_exact_gate_requires_safety_and_coverage(self) -> None:
        examples = []
        for index in range(MINIMUM_SELECTED):
            accepted = index < 500
            examples.append(
                row(
                    key=f"train:{index}",
                    truth="1234",
                    detector="1234" if accepted else "1294",
                    forest="1234" if accepted else "1284",
                    gray="1234" if accepted else "",
                    autocontrast="1234" if accepted else "",
                    baseline_claim="1294" if index < 200 else "1234",
                )
            )
        policy = POLICY_BY_NAME[
            "detector_forest_no_equal_length_conflict"
        ]
        summary = exact_summary(
            examples,
            policy,
            adjudicated=False,
        )
        self.assertGreaterEqual(summary["accepted"], MINIMUM_ACCEPTED)
        self.assertGreaterEqual(
            summary["coverage_lower"], MINIMUM_COVERAGE_LOWER
        )
        self.assertGreaterEqual(summary["reduction_lower"], TARGET_REDUCTION)
        self.assertTrue(summary["pass"])


if __name__ == "__main__":
    unittest.main()
