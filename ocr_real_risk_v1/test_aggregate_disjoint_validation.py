from __future__ import annotations

import unittest

from .aggregate_disjoint_validation import deduplicate_physical_evidence


def observation(process_digit: str, *, truth: str = "4000") -> dict[str, object]:
    return {
        "_process_key": process_digit * 64,
        "_shard_index": int(process_digit, 16),
        "document_id": f"doc-{process_digit}",
        "source_sha256": "a" * 64,
        "page_number": 33,
        "bbox_pt": [301.085, 381.684, 330.941, 392.784],
        "bbox_px": [833, 1054, 923, 1098],
        "truth": truth,
        "crop_id": "3158d53a21f0fcc59a4a",
        "crop_sha256": "b" * 64,
        "selection_rank_sha256": "c" * 64,
        "native_index_selection_rank_sha256": "d" * 64,
        "url_sha256": process_digit * 64,
        "tesseract_claim": truth,
        "claim_correct": True,
        "verifier_status": "INDETERMINATE",
        "verifier_prediction": "",
        "accepted": False,
        "false_accepted": False,
        "counterfactual_claim": "5000",
        "counterfactual_status": "INDETERMINATE",
        "counterfactual_prediction": "",
        "counterfactual_false_accept": False,
        "tesseract_runtime_ms": 90.0,
        "verifier_runtime_ms": 3.0,
    }


class AggregateEvidenceTests(unittest.TestCase):
    def test_identical_physical_evidence_is_counted_once_for_risk(self) -> None:
        first = observation("1")
        second = observation("e")
        unique, reuse = deduplicate_physical_evidence([second, first])
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["_process_key"], "1" * 64)
        self.assertEqual(reuse["process_associated_locations"], 2)
        self.assertEqual(reuse["unique_physical_locations"], 1)
        self.assertEqual(reuse["duplicate_process_associations"], 1)
        self.assertEqual(reuse["reused_physical_location_groups"], 1)
        self.assertEqual(reuse["groups"][0]["associated_process_count"], 2)
        self.assertTrue(reuse["groups"][0]["outcomes_identical"])

    def test_conflicting_truth_for_same_location_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "conflicting truth"):
            deduplicate_physical_evidence(
                [observation("1", truth="4000"), observation("e", truth="5000")]
            )

    def test_distinct_bboxes_remain_distinct_risk_units(self) -> None:
        first = observation("1")
        second = observation("e")
        second["bbox_pt"] = [302.0, 381.684, 330.941, 392.784]
        unique, reuse = deduplicate_physical_evidence([first, second])
        self.assertEqual(len(unique), 2)
        self.assertEqual(reuse["duplicate_process_associations"], 0)
        self.assertEqual(reuse["reused_physical_location_groups"], 0)


if __name__ == "__main__":
    unittest.main()
