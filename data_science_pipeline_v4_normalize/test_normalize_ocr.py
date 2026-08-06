from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normalize_ocr import canonical_bytes, normalized_token, token_kind, write_jsonl


class NormalizeUnitTests(unittest.TestCase):
    def test_normalized_token(self):
        self.assertEqual(normalized_token("Contratación"), "contratacion")
        self.assertEqual(normalized_token("L. 1,250.00"), "l125000")

    def test_token_kind(self):
        self.assertEqual(token_kind("*", ""), "punctuation")
        self.assertEqual(token_kind("2024", "2024"), "number")
        self.assertEqual(token_kind("ONCAE", "oncae"), "word")

    def test_canonical_bytes_are_stable(self):
        self.assertEqual(canonical_bytes({"b": 2, "a": 1}), b'{"a":1,"b":2}\n')

    def test_jsonl_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rows.jsonl"
            meta = write_jsonl(path, [{"z": 1}, {"a": 2}])
            self.assertEqual(meta["rows"], 2)
            self.assertEqual(path.read_text(), '{"z":1}\n{"a":2}\n')


if __name__ == "__main__":
    unittest.main()
