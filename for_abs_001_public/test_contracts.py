from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from for_abs_001_public.contracts import (
    EvidenceState,
    canonical_json,
    load_and_validate,
    sha256_payload,
    validate_receipt,
)


RECEIPTS = Path(__file__).with_name("receipts.json")


class ForensicPublicContractTests(unittest.TestCase):
    def test_receipts_are_valid(self) -> None:
        result = load_and_validate(RECEIPTS)
        self.assertTrue(result["valid"], result["errors"])

    def test_unlabeled_is_not_clean(self) -> None:
        self.assertEqual(EvidenceState.UNLABELED.value, "UNLABELED")
        self.assertNotEqual(EvidenceState.UNLABELED.value, "CLEAN")

    def test_stage2_requires_all_gates(self) -> None:
        payload = json.loads(RECEIPTS.read_text(encoding="utf-8"))
        receipt = copy.deepcopy(payload["receipts"]["stage2"])
        receipt["gates"]["unlabeled_not_clean"] = False
        self.assertIn("stage2:gates", validate_receipt("stage2", receipt))

    def test_stage2_requires_provenance_complete_cohort(self) -> None:
        payload = json.loads(RECEIPTS.read_text(encoding="utf-8"))
        receipt = copy.deepcopy(payload["receipts"]["stage2"])
        receipt["metrics"]["provenance_complete_positive_documents"] = 0
        self.assertIn(
            "stage2:positive-documents",
            validate_receipt("stage2", receipt),
        )

    def test_wrapper_forgery_is_rejected(self) -> None:
        payload = json.loads(RECEIPTS.read_text(encoding="utf-8"))
        payload["receipts"]["stage2"]["metrics"][
            "provenance_complete_positive_pages"
        ] = 999999
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forged.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = load_and_validate(path)
        self.assertFalse(result["valid"])
        self.assertIn("wrapper-hash", result["errors"])

    def test_canonical_hash_is_order_invariant(self) -> None:
        left = {"b": 2, "a": {"y": 1, "x": 0}}
        right = {"a": {"x": 0, "y": 1}, "b": 2}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(sha256_payload(left), sha256_payload(right))


if __name__ == "__main__":
    unittest.main()
