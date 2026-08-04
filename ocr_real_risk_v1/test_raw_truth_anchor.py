from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .raw_truth_anchor import (
    anchored_native_truths,
    build_raw_url_anchor_map,
    release_common_anchors,
)


class RawTruthAnchorTests(unittest.TestCase):
    def test_url_bound_map_uses_common_and_document_specific_metadata(self) -> None:
        release = {
            "ocid": "ocds-test-110509-2025",
            "date": "2025-08-04T12:34:56Z",
            "tender": {
                "id": "PROCESS-110509",
                "title": "Reposición del sistema, código 110509",
                "documents": [
                    {
                        "id": "DOC-123456",
                        "url": "https://example.test/a-999999-2025.pdf",
                        "title": "Lote 123456",
                        "documentType": "biddingDocuments",
                    },
                    {
                        "id": "DOC-654321",
                        "url": "https://example.test/b-888888-2025.pdf",
                        "title": "Lote 654321",
                        "documentType": "clarifications",
                    },
                ],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oncae_2025.jsonl"
            path.write_text(json.dumps(release) + "\n", encoding="utf-8")
            mapping, census = build_raw_url_anchor_map([path])

        first = mapping["https://example.test/a-999999-2025.pdf"]
        second = mapping["https://example.test/b-888888-2025.pdf"]
        self.assertIn("110509", first)
        self.assertIn("123456", first)
        self.assertNotIn("654321", first)
        self.assertIn("110509", second)
        self.assertIn("654321", second)
        self.assertNotIn("123456", second)
        self.assertNotIn("2025", first)
        self.assertNotIn("999999", first)
        self.assertEqual(census["urls_with_anchors"], 2)

    def test_date_fields_are_excluded_but_structured_amounts_remain(self) -> None:
        release = {
            "date": "2025-08-04T12:34:56Z",
            "award": {"value": {"amount": 9158922.75}},
            "description": "Proyecto 108919",
        }
        anchors = release_common_anchors(release)
        self.assertIn("9158922", anchors)
        self.assertIn("108919", anchors)
        self.assertNotIn("20250804123456", anchors)

    def test_native_truth_requires_same_url_anchor(self) -> None:
        mapping = {"https://example.test/a.pdf": {"110509"}}
        self.assertEqual(
            anchored_native_truths(
                "https://example.test/a.pdf",
                ["110509", "999999", "2025"],
                mapping,
            ),
            ["110509"],
        )
        self.assertEqual(
            anchored_native_truths(
                "https://example.test/b.pdf",
                ["110509"],
                mapping,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
