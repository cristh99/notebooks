from __future__ import annotations

import inspect
import unittest

from ocr_real_risk_v1.numeric_consensus_policy_v7 import (
    FOREST_MINIMUM_MEAN_PROBABILITY,
    inference_eligibility,
    policy_manifest,
    predict_v7_claim_verifier,
)


def row(
    *,
    claim: str = "1234",
    forest: str = "1234",
    probability: float = 0.25,
    gray: str = "1234",
    autocontrast: str = "",
    conflicts: list[str] | None = None,
) -> dict:
    return {
        "candidate": {
            "claim": claim,
            "prediction": forest,
            "minimum_mean_probability": probability,
            "matched": {
                "text": claim,
                "equal_length_conflicts": conflicts or [],
                "match": {"truth_coverage": 0.8},
            },
            "guard": {
                "readings": {
                    "gray": {"digits": gray},
                    "autocontrast": {"digits": autocontrast},
                }
            },
        }
    }


class NumericConsensusPolicyV7Tests(unittest.TestCase):
    def test_eligibility_has_no_truth_parameter(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(inference_eligibility).parameters),
            ("matched",),
        )

    def test_eligibility_accepts_visible_numeric_claim(self) -> None:
        claim, eligible, reason = inference_eligibility(
            {
                "text": "123456",
                "match": {"truth_coverage": 0.75},
            }
        )
        self.assertEqual(claim, "123456")
        self.assertTrue(eligible)
        self.assertEqual(
            reason, "ELIGIBLE_INFERENCE_VISIBLE_NUMERIC_CLAIM"
        )

    def test_eligibility_rejects_low_geometry_coverage(self) -> None:
        _, eligible, reason = inference_eligibility(
            {"text": "1234", "match": {"truth_coverage": 0.49}}
        )
        self.assertFalse(eligible)
        self.assertEqual(reason, "LOW_SPATIAL_COVERAGE")

    def test_exact_threshold_is_effective(self) -> None:
        self.assertEqual(
            predict_v7_claim_verifier(
                row(probability=FOREST_MINIMUM_MEAN_PROBABILITY)
            ),
            "1234",
        )
        self.assertIsNone(
            predict_v7_claim_verifier(
                row(
                    probability=(
                        FOREST_MINIMUM_MEAN_PROBABILITY - 1e-12
                    )
                )
            )
        )

    def test_forest_must_verify_claim(self) -> None:
        self.assertIsNone(
            predict_v7_claim_verifier(row(forest="1235"))
        )

    def test_at_least_one_guard_must_verify_claim(self) -> None:
        self.assertIsNone(
            predict_v7_claim_verifier(
                row(gray="9999", autocontrast="8888")
            )
        )
        self.assertEqual(
            predict_v7_claim_verifier(
                row(gray="9999", autocontrast="1234")
            ),
            "1234",
        )

    def test_equal_length_conflict_forces_abstention(self) -> None:
        self.assertIsNone(
            predict_v7_claim_verifier(row(conflicts=["9234"]))
        )

    def test_counterfactual_claim_is_not_corrected(self) -> None:
        counterfactual = row(
            claim="1235",
            forest="1234",
            gray="1234",
            autocontrast="1234",
        )
        self.assertIsNone(
            predict_v7_claim_verifier(counterfactual)
        )

    def test_policy_never_returns_alternate_output(self) -> None:
        altered = row(
            claim="9234",
            forest="1234",
            gray="1234",
            autocontrast="1234",
        )
        self.assertIsNone(predict_v7_claim_verifier(altered))

    def test_manifest_binds_no_oracle_and_effective_threshold(self) -> None:
        manifest = policy_manifest()
        self.assertFalse(
            manifest["ground_truth_available_at_inference"]
        )
        self.assertFalse(
            manifest["annotation_text_length_used_at_inference"]
        )
        self.assertTrue(manifest["forest_threshold_is_effective"])
        self.assertEqual(
            manifest["forest_minimum_mean_probability"], 0.25
        )
        self.assertFalse(manifest["alternate_output_correction"])


if __name__ == "__main__":
    unittest.main()
