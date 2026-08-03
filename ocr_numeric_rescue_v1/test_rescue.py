from __future__ import annotations

import copy
import unittest

from .rescue import (
    RescuePolicy,
    align_prediction_to_reference,
    apply_policy,
    classify_candidate,
    digest_payload,
    numeric_tokens,
    sequence_accuracy,
    summarize_candidates,
)
from .verify_report import SCHEMA, stable_payload, verify


class RescueTests(unittest.TestCase):
    def test_numeric_tokens(self):
        self.assertEqual(numeric_tokens("L 1,234.50 and 17%"), ("1,234.50", "17%"))

    def test_alignment_match_substitution(self):
        aligned = align_prediction_to_reference(("10", "20", "30"), ("10", "21", "30"))
        self.assertEqual([item["state"] for item in aligned["assignments"]], ["MATCH", "SUBSTITUTION", "MATCH"])
        self.assertEqual(aligned["assignments"][1]["target"], "20")

    def test_alignment_insertion_deletion(self):
        inserted = align_prediction_to_reference(("10",), ("9", "10"))
        self.assertIn("INSERTION", [item["state"] for item in inserted["assignments"]])
        deleted = align_prediction_to_reference(("9", "10"), ("10",))
        self.assertEqual(len(deleted["deletions"]), 1)

    def test_sequence_accuracy(self):
        self.assertEqual(sequence_accuracy(("1", "2"), ("1", "3")), 0.5)

    def test_true_correction(self):
        candidate = {
            "baseline_token": "21",
            "paddle_token": "20",
            "tesseract_confidence": 0.50,
            "paddle_confidence": 0.99,
            "alignment_state": "SUBSTITUTION",
            "target_token": "20",
        }
        result = classify_candidate(candidate, RescuePolicy())
        self.assertTrue(result["propose_change"])
        self.assertEqual(result["outcome"], "TRUE_CORRECTION")

    def test_harmful_change(self):
        candidate = {
            "baseline_token": "20",
            "paddle_token": "28",
            "tesseract_confidence": 0.50,
            "paddle_confidence": 0.99,
            "alignment_state": "MATCH",
            "target_token": "20",
        }
        self.assertEqual(classify_candidate(candidate, RescuePolicy())["outcome"], "HARMFUL_CHANGE")

    def test_summary(self):
        policy = RescuePolicy()
        candidates = apply_policy(
            [
                {"baseline_token": "21", "paddle_token": "20", "tesseract_confidence": 0.5, "paddle_confidence": 0.99, "alignment_state": "SUBSTITUTION", "target_token": "20"},
                {"baseline_token": "30", "paddle_token": "30", "tesseract_confidence": 0.9, "paddle_confidence": 0.99, "alignment_state": "MATCH", "target_token": "30"},
            ],
            policy,
        )
        summary = summarize_candidates(candidates)
        self.assertEqual(summary["strict_true_corrections"], 1)
        self.assertEqual(summary["strict_harmful_changes"], 0)

    def test_verifier_rejects_tamper(self):
        policy = RescuePolicy()
        candidate = {
            "candidate_id": "p:0",
            "page_id": "p",
            "baseline_index": 0,
            "baseline_token": "21",
            "paddle_token": "20",
            "tesseract_confidence": 0.5,
            "paddle_confidence": 0.99,
            "alignment_state": "SUBSTITUTION",
            "target_token": "20",
        }
        candidate["decision"] = classify_candidate(candidate, policy)
        candidates = [candidate]
        pages = [{
            "page_id": "p",
            "reference_numbers": ["20"],
            "baseline_numbers": ["21"],
            "strict_rescued_numbers": ["20"],
            "baseline_numeric_accuracy": 0.0,
            "strict_numeric_accuracy": 1.0,
        }]
        report = {
            "schema": SCHEMA,
            "source_canary": {"run_id": 30833428126, "artifact_id": 8864530547},
            "dataset": {"revision": "x", "selected_pages": ["p"]},
            "policy": policy.to_data(),
            "pages": pages,
            "candidates": candidates,
            "metrics": {"candidate_summary": summarize_candidates(candidates), "baseline_numeric_accuracy": 0.0, "strict_numeric_accuracy": 1.0, "strict_delta_pp": 100.0},
            "denominators": {"pages": 1, "candidates": 1},
            "constraints": {"external_spend_usd": 0, "gcloud_used": False, "paid_api_used": False, "gpu_used": False},
        }
        report["stable_payload_sha256"] = digest_payload(stable_payload(report))
        self.assertEqual(verify(report), [])
        forged = copy.deepcopy(report)
        forged["candidates"][0]["paddle_token"] = "99"
        forged["stable_payload_sha256"] = digest_payload(stable_payload(forged))
        self.assertTrue(verify(forged))


if __name__ == "__main__":
    unittest.main()
