from __future__ import annotations

import unittest

from .wildreceipt_v6_policy_lab import (
    MINIMUM_ACCEPTED,
    MINIMUM_COVERAGE_LOWER,
    MINIMUM_SELECTED,
    TARGET_REDUCTION,
    exact_summary,
    policy_crop_unanimous,
    policy_detector_forest_no_conflict,
    policy_detector_forest_or_crop_unanimous,
)


def row(
    *,
    truth: str = "1234",
    detector: str = "1234",
    forest: str = "1234",
    gray: str = "1234",
    autocontrast: str = "1234",
    conflict: bool = False,
    baseline_claim: str = "1234",
    counterfactual: str = "1235",
) -> dict:
    return {
        "key": "train-00000-of-00002:1",
        "truth": truth,
        "counterfactual_claim": counterfactual,
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


class WildReceiptV6PolicyLabTests(unittest.TestCase):
    def test_detector_forest_anchor_rejects_equal_length_conflict(self) -> None:
        self.assertEqual(policy_detector_forest_no_conflict(row()), "1234")
        self.assertIsNone(
            policy_detector_forest_no_conflict(row(conflict=True))
        )
        self.assertIsNone(
            policy_detector_forest_no_conflict(row(forest="1235"))
        )

    def test_crop_unanimity_can_correct_detector(self) -> None:
        example = row(
            truth="1234",
            detector="1284",
            forest="1234",
            gray="1234",
            autocontrast="1234",
        )
        self.assertEqual(policy_crop_unanimous(example), "1234")
        self.assertEqual(
            policy_detector_forest_or_crop_unanimous(example), "1234"
        )

    def test_union_fails_closed_on_competing_consensus(self) -> None:
        example = row(
            detector="1234",
            forest="1234",
            gray="1294",
            autocontrast="1294",
        )
        self.assertEqual(
            policy_detector_forest_or_crop_unanimous(example), "1234"
        )
        competing = row(
            detector="1234",
            forest="1234",
            gray="1294",
            autocontrast="1294",
            conflict=True,
        )
        self.assertIsNone(
            policy_detector_forest_or_crop_unanimous(competing)
        )

    def test_exact_gate_requires_coverage_and_safety(self) -> None:
        rows = []
        for index in range(MINIMUM_SELECTED):
            truth = "1234"
            baseline = "1294" if index < 200 else truth
            accepted = index < 500
            example = row(
                truth=truth,
                detector=truth if accepted else "1294",
                forest=truth if accepted else "1294",
                gray=truth if accepted else "",
                autocontrast=truth if accepted else "",
                baseline_claim=baseline,
            )
            rows.append(example)
        summary = exact_summary(
            rows,
            policy_detector_forest_no_conflict,
            adjudicated=False,
        )
        self.assertGreaterEqual(summary["accepted"], MINIMUM_ACCEPTED)
        self.assertGreaterEqual(
            summary["coverage_lower"], MINIMUM_COVERAGE_LOWER
        )
        self.assertGreaterEqual(summary["reduction_lower"], TARGET_REDUCTION)
        self.assertTrue(summary["pass"])

        rows[0]["candidate"]["prediction"] = "1294"
        unsafe = exact_summary(
            rows,
            policy_detector_forest_no_conflict,
            adjudicated=False,
        )
        self.assertLess(unsafe["accepted"], summary["accepted"])


if __name__ == "__main__":
    unittest.main()
