from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from resolve_ensemble import SOURCE_ENTITY_ID, resolve, source_bound_oncae


class EnsembleResolverTests(unittest.TestCase):
    def test_source_binding_does_not_require_ocr_mention(self) -> None:
        row = source_bound_oncae([], [])
        self.assertEqual(row["entity_id"], SOURCE_ENTITY_ID)
        self.assertEqual(row["resolution_method"], "trusted_source_host_registry")
        self.assertEqual(row["mention_count"], 0)
        self.assertEqual(row["evidence_line_ids"], [])

    def test_source_binding_preserves_optional_text_lineage(self) -> None:
        row = source_bound_oncae(
            [{"entity_id": SOURCE_ENTITY_ID, "mention_count": 1}],
            [{"entity_id": SOURCE_ENTITY_ID, "line_ids": ["line-2", "line-1"]}],
        )
        self.assertEqual(row["mention_count"], 1)
        self.assertEqual(row["evidence_line_ids"], ["line-1", "line-2"])

    def test_untrusted_source_host_fails_before_input_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "untrusted source host"):
                resolve(Path(tmp) / "missing", Path(tmp) / "out", "example.com")


if __name__ == "__main__":
    unittest.main()
