from __future__ import annotations

import copy
import unittest

from PIL import Image

from .sroie_candidate_lab import (
    PIXEL_VIEW_NAMES,
    base_accept,
    claim_features,
    deterministic_views,
    metric_payload,
)


def _position(claim: str, predicted: str, score: float = 0.70) -> list[dict]:
    return [
        {
            "index": index,
            "claim": expected,
            "predicted": observed,
            "state": "ALIGNED" if expected == observed else "INDETERMINATE",
            "top_score": score,
            "claim_score": score if expected == observed else score - 0.08,
            "top_margin": 0.02,
            "mismatch_delta": 0.0 if expected == observed else 0.08,
        }
        for index, (expected, observed) in enumerate(zip(claim, predicted, strict=True))
    ]


def _pixel(claim: str, predicted: str | None = None, status: str = "INDETERMINATE") -> dict:
    prediction = predicted or claim
    return {
        name: {
            "status": status if name == "original" else "INDETERMINATE",
            "claim": claim,
            "predicted": prediction,
            "cuts": [0, 1],
            "positions": _position(claim, prediction),
        }
        for name in PIXEL_VIEW_NAMES
    }


def _ocr(claim: str, conflict: str | None = None) -> dict:
    outputs = [claim, claim, claim, conflict or claim]
    return {
        str(index): {
            "text": value,
            "digits": value,
            "psm": 7,
            "timeout": False,
            "wall_seconds": 0.01,
        }
        for index, value in enumerate(outputs)
    }


class SroieCandidateLabTests(unittest.TestCase):
    def test_views_are_deterministic_and_complete(self) -> None:
        image = Image.new("L", (20, 10), 255)
        first = deterministic_views(image)
        second = deterministic_views(image)
        self.assertEqual(tuple(first), PIXEL_VIEW_NAMES)
        self.assertEqual(tuple(second), PIXEL_VIEW_NAMES)
        for name in PIXEL_VIEW_NAMES:
            self.assertEqual(first[name].tobytes(), second[name].tobytes())
        self.assertEqual(first["original"].size, (20, 10))
        self.assertEqual(first["autocontrast2"].size, (40, 20))

    def test_claim_features_count_consensus(self) -> None:
        features = claim_features(
            "1234",
            _pixel("1234"),
            _ocr("1234"),
            full_page_confidence=91.0,
        )
        self.assertEqual(features["predicted_views"], 4)
        self.assertEqual(features["minimum_position_vote"], 4)
        self.assertEqual(features["exact_ocr_votes"], 4)
        self.assertEqual(features["ocr_equal_length_conflicts"], [])

    def test_extension_requires_no_equal_length_conflict(self) -> None:
        rule = {
            "retain_original_strict": False,
            "predicted_views_min": 3,
            "position_vote_min": 3,
            "position_median_claim_score_min": 0.60,
            "ocr_exact_votes_min": 2,
            "full_page_confidence_min": 80.0,
        }
        clean = claim_features(
            "1234",
            _pixel("1234"),
            _ocr("1234"),
            full_page_confidence=90.0,
        )
        self.assertTrue(base_accept(clean, rule))
        conflict = claim_features(
            "1234",
            _pixel("1234"),
            _ocr("1234", conflict="1284"),
            full_page_confidence=90.0,
        )
        self.assertFalse(base_accept(conflict, rule))

    def test_original_strict_is_optional(self) -> None:
        strict_features = claim_features(
            "1234",
            _pixel("1234", status="ALIGNED"),
            _ocr("9999", conflict="9999"),
            full_page_confidence=10.0,
        )
        base_rule = {
            "retain_original_strict": False,
            "predicted_views_min": 4,
            "position_vote_min": 4,
            "position_median_claim_score_min": 0.70,
            "ocr_exact_votes_min": 4,
            "full_page_confidence_min": 99.0,
        }
        self.assertFalse(base_accept(strict_features, base_rule))
        retained = dict(base_rule)
        retained["retain_original_strict"] = True
        self.assertTrue(base_accept(strict_features, retained))

    def test_metrics_separate_natural_and_counterfactual_risk(self) -> None:
        rule = {
            "retain_original_strict": False,
            "predicted_views_min": 3,
            "position_vote_min": 3,
            "position_median_claim_score_min": 0.60,
            "ocr_exact_votes_min": 2,
            "full_page_confidence_min": 80.0,
        }
        accepted = claim_features(
            "1234", _pixel("1234"), _ocr("1234"), full_page_confidence=90.0
        )
        rejected = copy.deepcopy(accepted)
        rejected["ocr_equal_length_conflicts"] = ["1284"]
        rows = [
            {
                "claim_correct": True,
                "natural_features": accepted,
                "counterfactual_features": rejected,
            },
            {
                "claim_correct": False,
                "natural_features": rejected,
                "counterfactual_features": accepted,
            },
        ]
        metrics = metric_payload(rows, rule)
        self.assertEqual(metrics["accepted"], 1)
        self.assertEqual(metrics["natural_false_accepts"], 0)
        self.assertEqual(metrics["counterfactual_false_accepts"], 1)


if __name__ == "__main__":
    unittest.main()
