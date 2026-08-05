from __future__ import annotations

import copy
import unittest

from PIL import Image

from .sroie_aggregate import deduplicate_physical_evidence, exact_summary
from .sroie_natural_holdout import (
    canonical_numeric_region,
    crop_box,
    eligibility,
    match_ocr_claim,
    select_numeric_annotation,
    stable_payload,
    verify_stable_payload,
)


class SroieNaturalHoldoutTests(unittest.TestCase):
    def test_numeric_scope_is_explicit(self) -> None:
        self.assertEqual(canonical_numeric_region("RM 1,234.50"), "123450")
        self.assertEqual(canonical_numeric_region("25/12/2018"), "25122018")
        self.assertEqual(canonical_numeric_region("00001234"), "00001234")
        self.assertIsNone(canonical_numeric_region("2018"))
        self.assertIsNone(canonical_numeric_region("TD01167104"))
        self.assertIsNone(canonical_numeric_region("111111"))
        self.assertIsNone(canonical_numeric_region("12"))

    def test_selection_is_outcome_blind_and_order_independent(self) -> None:
        kwargs = {
            "split": "train",
            "key": "X00000000001",
            "image_sha256": "a" * 64,
        }
        words = ["RM 12.30", "2018", "4567", "NOT NUMERIC"]
        boxes = [[10, 10, 50, 30], [60, 10, 90, 30], [10, 40, 50, 60], [0, 0, 9, 9]]
        first, first_counts = select_numeric_annotation(
            words=words,
            bboxes=boxes,
            **kwargs,
        )
        second, second_counts = select_numeric_annotation(
            words=list(reversed(words)),
            bboxes=list(reversed(boxes)),
            **kwargs,
        )
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(first_counts, second_counts)
        self.assertIn(first["truth"], {"1230", "4567"})
        self.assertEqual(len(first["selection_rank_sha256"]), 64)

    def test_spatial_match_dominates_remote_high_confidence_token(self) -> None:
        truth_bbox = [100, 100, 160, 130]
        tokens = [
            {"text": "9999", "digits": "9999", "bbox": [300, 300, 360, 330], "confidence": 99.0},
            {"text": "1234", "digits": "1234", "bbox": [98, 99, 162, 131], "confidence": 70.0},
        ]
        matched = match_ocr_claim(truth_bbox, tokens)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["digits"], "1234")
        claim, eligible, reason = eligibility("1234", matched)
        self.assertEqual(claim, "1234")
        self.assertTrue(eligible)
        self.assertEqual(reason, "ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM")

    def test_length_mismatch_and_low_coverage_abstain(self) -> None:
        claim, eligible, reason = eligibility(
            "1234",
            {"text": "12345", "match": {"truth_coverage": 1.0}},
        )
        self.assertEqual(claim, "12345")
        self.assertFalse(eligible)
        self.assertEqual(reason, "LENGTH_MISMATCH_OUTSIDE_SUBSTITUTION_SCOPE")
        claim, eligible, reason = eligibility(
            "1234",
            {"text": "1234", "match": {"truth_coverage": 0.49}},
        )
        self.assertEqual(claim, "1234")
        self.assertFalse(eligible)
        self.assertEqual(reason, "LOW_SPATIAL_COVERAGE")

    def test_crop_is_clipped(self) -> None:
        image = Image.new("RGB", (100, 80), "white")
        self.assertEqual(crop_box(image, [-2, 5, 30, 20], margin=2), (0, 3, 32, 22))

    def test_stable_payload_detects_mutation(self) -> None:
        sealed = stable_payload({"schema": "test/1", "value": 7}, "manifest_sha256")
        self.assertTrue(verify_stable_payload(sealed, "manifest_sha256"))
        changed = dict(sealed)
        changed["value"] = 8
        self.assertFalse(verify_stable_payload(changed, "manifest_sha256"))

    @staticmethod
    def _observation(*, key: str, split: str, truth: str = "1234") -> dict:
        return {
            "evidence_key": "e" * 64,
            "split": split,
            "row_index": 1 if split == "train" else 2,
            "key": key,
            "image_sha256": "a" * 64,
            "image_width": 500,
            "image_height": 900,
            "company": "COMPANY",
            "company_group": "COMPANY",
            "truth": truth,
            "annotation_text": truth,
            "bbox": [10, 20, 60, 50],
            "selection_rank_sha256": "b" * 64,
            "tesseract": {
                "claim": truth,
                "eligible": True,
                "eligibility_reason": "ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM",
                "claim_correct": True,
                "matched": {
                    "text": truth,
                    "digits": truth,
                    "bbox": [10, 20, 60, 50],
                    "confidence": 90.0,
                    "match": {
                        "iou": 1.0,
                        "truth_coverage": 1.0,
                        "token_coverage": 1.0,
                        "center_distance": 0.0,
                        "score": 4.5,
                    },
                },
                "page_runtime": {
                    "wall_seconds": 1.0,
                    "numeric_tokens": 1,
                    "invalid_numeric_boxes_filtered": 0,
                    "timeout": False,
                },
            },
            "verifier": {
                "crop_source": "tesseract_matched_bbox",
                "crop_box": [8, 18, 62, 52],
                "crop_file": "crops/e.png",
                "crop_sha256": "c" * 64,
                "status": "ALIGNED",
                "prediction": truth,
                "accepted": True,
                "correct_accept": True,
                "false_accept": False,
                "runtime_seconds": 0.003,
            },
            "counterfactual": {
                "claim": "1235",
                "status": "MISALIGNED",
                "prediction": "",
                "false_accept": False,
                "runtime_seconds": 0.003,
            },
        }

    def test_duplicate_physical_evidence_is_one_risk_unit(self) -> None:
        first = self._observation(key="A", split="train")
        second = copy.deepcopy(first)
        second["key"] = "B"
        second["split"] = "test"
        second["row_index"] = 2
        unique, reuse = deduplicate_physical_evidence([first, second])
        self.assertEqual(len(unique), 1)
        self.assertEqual(reuse["receipt_associated_locations"], 2)
        self.assertEqual(reuse["unique_physical_locations"], 1)
        self.assertEqual(reuse["duplicate_receipt_associations"], 1)

    def test_duplicate_truth_conflict_fails_closed(self) -> None:
        first = self._observation(key="A", split="train")
        second = self._observation(key="B", split="test", truth="9999")
        with self.assertRaisesRegex(RuntimeError, "conflicting annotation"):
            deduplicate_physical_evidence([first, second])

    def test_predeclared_exact_gate_can_pass_only_with_natural_errors(self) -> None:
        rows = []
        for index in range(600):
            wrong = index < 120
            rows.append(
                {
                    "tesseract": {
                        "eligible": True,
                        "claim_correct": not wrong,
                    },
                    "verifier": {
                        "accepted": not wrong,
                        "false_accept": False,
                    },
                    "counterfactual": {"false_accept": False},
                }
            )
        summary = exact_summary(rows, minimum_accepted=100)
        self.assertEqual(summary["selected"], 600)
        self.assertEqual(summary["baseline_false"], 120)
        self.assertEqual(summary["accepted"], 480)
        self.assertTrue(summary["pass"])


if __name__ == "__main__":
    unittest.main()
