from __future__ import annotations

import unittest

from .adapter import LABELS
from .adapter_v3 import value_by_year_fallback


class AdapterV3Tests(unittest.TestCase):
    def test_uses_second_xbrl_concept_when_first_has_no_requested_year(self) -> None:
        statement = {
            "income_statement": {
                "line_items": {
                    LABELS["revenue"][0]: {
                        "periods": {"FY2010": {"value": 10.0}}
                    },
                    LABELS["revenue"][1]: {
                        "periods": {"FY2025": {"value": 100.0}}
                    },
                }
            }
        }
        self.assertEqual(
            value_by_year_fallback(
                statement, "income_statement", "revenue", "FY2025"
            ),
            100.0,
        )

    def test_does_not_sum_overlapping_xbrl_concepts(self) -> None:
        statement = {
            "income_statement": {
                "line_items": {
                    LABELS["revenue"][0]: {
                        "periods": {"FY2025": {"value": 100.0}}
                    },
                    LABELS["revenue"][1]: {
                        "periods": {"FY2025": {"value": 200.0}}
                    },
                }
            }
        }
        self.assertEqual(
            value_by_year_fallback(
                statement, "income_statement", "revenue", "FY2025"
            ),
            100.0,
        )

    def test_returns_none_when_no_mapped_concept_has_year(self) -> None:
        statement = {
            "income_statement": {
                "line_items": {
                    LABELS["revenue"][0]: {
                        "periods": {"FY2024": {"value": 100.0}}
                    }
                }
            }
        }
        self.assertIsNone(
            value_by_year_fallback(
                statement, "income_statement", "revenue", "FY2025"
            )
        )


if __name__ == "__main__":
    unittest.main()
