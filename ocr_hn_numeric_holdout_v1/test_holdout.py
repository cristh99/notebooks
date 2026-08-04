from __future__ import annotations

import unittest

import fitz
from PIL import Image, ImageDraw

from .core import (
    absolute_risk_gate,
    canonical_digits,
    clopper_pearson_lower,
    clopper_pearson_upper,
    extract_digit_runs,
    extract_record_documents,
    match_ocr_claim,
    one_digit_counterfactual,
    risk_gate,
    stable_manifest,
    verify_manifest_hash,
)
from .evaluate import apply_page_tier, eligibility, png_bytes
from .prepare import build_ocid_units, round_robin_units
from .verify import semantic_equal


class HoldoutTests(unittest.TestCase):
    def test_vector_pdf_digit_extraction(self) -> None:
        document = fitz.open()
        page = document.new_page(width=300, height=200)
        page.insert_text((40, 70), "Contrato 109071 y referencia 2024", fontsize=12)
        payload = document.tobytes()
        document.close()
        runs, summary = extract_digit_runs(payload, minimum_length=4)
        truths = {run.truth for run in runs}
        self.assertIn("109071", truths)
        self.assertIn("2024", truths)
        self.assertEqual(summary["reason"], "OK")

    def test_parent_institution_and_documents(self) -> None:
        record = {
            "ocid": "ocds-test-x",
            "compiledRelease": {
                "parties": [
                    {
                        "name": "Unidad Central",
                        "roles": ["buyer"],
                        "memberOf": [{"name": "Secretaría de Salud"}],
                    }
                ],
                "tender": {
                    "documents": [
                        {
                            "id": 1,
                            "url": "http://example.test/a.pdf",
                            "documentType": "biddingDocuments",
                        }
                    ]
                },
            },
        }
        rows = extract_record_documents(record, 7)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["institution"], "Secretaría de Salud")
        self.assertEqual(rows[0]["api_page"], 7)

    def test_ocid_grouping_and_round_robin(self) -> None:
        rows = [
            {"ocid": "a1", "institution": "A", "url": "u1", "metadata_selector_key": "1", "document_type_priority": 0},
            {"ocid": "a1", "institution": "A", "url": "u2", "metadata_selector_key": "2", "document_type_priority": 1},
            {"ocid": "a2", "institution": "A", "url": "u3", "metadata_selector_key": "3", "document_type_priority": 0},
            {"ocid": "b1", "institution": "B", "url": "u4", "metadata_selector_key": "4", "document_type_priority": 0},
            {"ocid": "b2", "institution": "B", "url": "u5", "metadata_selector_key": "5", "document_type_priority": 0},
        ]
        units = build_ocid_units(rows)
        self.assertEqual(len(units), 4)
        queue = list(round_robin_units(units))
        self.assertEqual({queue[0]["institution"], queue[1]["institution"]}, {"A", "B"})
        self.assertEqual(len(queue), 4)

    def test_manifest_hash(self) -> None:
        manifest = stable_manifest({"schema": "x", "crops": []})
        self.assertTrue(verify_manifest_hash(manifest))
        manifest["schema"] = "tampered"
        self.assertFalse(verify_manifest_hash(manifest))

    def test_exact_bounds_and_absolute_gate(self) -> None:
        self.assertEqual(clopper_pearson_lower(0, 100), 0.0)
        self.assertGreater(clopper_pearson_upper(0, 300), 0.0)
        self.assertLess(clopper_pearson_upper(0, 300), 0.02)
        gate = absolute_risk_gate(
            false_accepts=0,
            total=300,
            maximum_upper_risk=0.01,
            minimum_total=300,
        )
        self.assertTrue(gate["pass"])

    def test_tenfold_gate(self) -> None:
        result = risk_gate(
            baseline_false=60,
            baseline_total=300,
            candidate_false=0,
            candidate_total=300,
            eligible_total=300,
            minimum_accepted=200,
        )
        self.assertTrue(result["pass"])

    def test_match_claim_and_equal_length_eligibility(self) -> None:
        tokens = [
            {"text": "109071", "bbox": [10, 10, 70, 30], "confidence": 90},
            {"text": "999", "bbox": [100, 100, 140, 120], "confidence": 99},
        ]
        match = match_ocr_claim([12, 11, 68, 29], tokens)
        self.assertEqual(canonical_digits(match["text"]), "109071")
        self.assertGreater(match["match"]["truth_coverage"], 0.9)
        claim, eligible, reason = eligibility("109071", match)
        self.assertEqual(claim, "109071")
        self.assertTrue(eligible)
        self.assertEqual(reason, "ELIGIBLE_EQUAL_LENGTH_SPATIAL_CLAIM")
        _, eligible, reason = eligibility("10907", match)
        self.assertFalse(eligible)
        self.assertIn("LENGTH_MISMATCH", reason)

    def test_counterfactual(self) -> None:
        value = one_digit_counterfactual("109071", "case")
        self.assertEqual(len(value), 6)
        self.assertNotEqual(value, "109071")
        self.assertEqual(sum(a != b for a, b in zip(value, "109071")), 1)

    def test_stress_tier_is_deterministic_and_geometry_preserving(self) -> None:
        image = Image.new("RGB", (400, 200), "white")
        draw = ImageDraw.Draw(image)
        draw.text((20, 50), "109071", fill="black")
        first = apply_page_tier(image, "scan_stress_v1")
        second = apply_page_tier(image, "scan_stress_v1")
        self.assertEqual(first.size, image.size)
        self.assertEqual(png_bytes(first), png_bytes(second))

    def test_semantic_replay_ignores_only_json_numeric_spelling(self) -> None:
        self.assertTrue(semantic_equal({"factor": 10, "rows": [1, 0.5]}, {"factor": 10.0, "rows": [1.0, 0.5]}))
        self.assertFalse(semantic_equal({"pass": True}, {"pass": 1}))
        self.assertFalse(semantic_equal({"factor": 10}, {"factor": 10.1}))


if __name__ == "__main__":
    unittest.main()
