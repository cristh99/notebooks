from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .truth_anchor import (
    anchored_numbers,
    build_url_anchor_map,
    eligible_native_truths,
)


class TruthAnchorTests(unittest.TestCase):
    def test_extracts_project_numbers_but_not_years(self) -> None:
        values = anchored_numbers(
            "Proyecto 110509, contrato 000-001-01-00000524, gestión 2025"
        )
        self.assertIn("110509", values)
        self.assertIn("0000010100000524", values)
        self.assertNotIn("2025", values)

    def test_builds_url_specific_map(self) -> None:
        record = {
            "oncae_object_text": "Reposición, código 110509",
            "shared_code": "PROJECT:110509",
            "ocid_oncae": "ocds-test",
            "oncae_documents": [
                {
                    "url": "http://example.test/doc.pdf",
                    "title": "Contrato",
                    "documentType": "contractSigned",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            mapping, census = build_url_anchor_map(path)
        self.assertEqual(mapping["http://example.test/doc.pdf"], {"110509"})
        self.assertEqual(census["unique_urls"], 1)

    def test_native_truth_requires_structured_anchor(self) -> None:
        anchors = {"http://example.test/doc.pdf": {"110509"}}
        accepted = eligible_native_truths(
            "http://example.test/doc.pdf",
            ["110509", "999999", "2025"],
            anchors,
        )
        self.assertEqual(accepted, ["110509"])

    def test_wrong_document_does_not_borrow_anchor(self) -> None:
        anchors = {"http://example.test/a.pdf": {"110509"}}
        self.assertEqual(
            eligible_native_truths(
                "http://example.test/b.pdf",
                ["110509"],
                anchors,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
