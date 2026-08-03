from __future__ import annotations

import unittest

from .audit import SAMPLE_FIELDS, failure_url, financial_url


class FdicAuditTests(unittest.TestCase):
    def test_financial_url_contains_frozen_fields_and_date(self) -> None:
        url = financial_url("2008-12-31", True)
        self.assertIn("financials", url)
        self.assertIn("20081231", url)
        for field in SAMPLE_FIELDS:
            self.assertIn(field, url)

    def test_range_filter_variant_is_available(self) -> None:
        url = financial_url("2025-12-31", False)
        self.assertIn("2025-12-31", url)
        self.assertIn("financials", url)

    def test_failure_url_is_bounded_and_csv(self) -> None:
        url = failure_url()
        self.assertIn("failures", url)
        self.assertIn("limit=10000", url)
        self.assertIn("format=csv", url)


if __name__ == "__main__":
    unittest.main()
