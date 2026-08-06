from __future__ import annotations

import unittest

from resolve_pacc_provenance import SOURCE_URL


class ProvenanceTests(unittest.TestCase):
    def test_source_is_official_oncae_https(self):
        self.assertTrue(SOURCE_URL.startswith("https://oncae.gob.hn/"))


if __name__ == "__main__":
    unittest.main()
