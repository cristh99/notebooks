from __future__ import annotations

from datetime import date
import unittest

from data_science_dominance.fresh_gate_v1.record_extraction import (
    FundingEntry,
    ProjectRecord,
    canonical_project_name,
    extract_funding_entries,
    extract_project_records,
    latest_records_on_or_before,
    parse_amount,
    select_projects,
)


class RecordExtractionTests(unittest.TestCase):
    def test_project_name_canonicalization_is_conservative(self) -> None:
        self.assertEqual(
            canonical_project_name("Marie Canyon Green Streets (FEMA Project)"),
            "MARIE CANYON GREEN STREETS",
        )
        self.assertNotEqual(
            canonical_project_name("Westward Beach Road Repair Project"),
            canonical_project_name("Westward Beach Road Improvements Project"),
        )

    def test_extract_key_value_blocks_and_markdown_tables(self) -> None:
        text = """
# Civic Center Water Treatment Facility Phase 2
Date: 2022-12-15
Type: Capital
Status: Design

Project: Permanent Skate Park
Report Date: 2022-11-01
Project Type: capital
Project Status: design

| Project Name | Report Date | Type | Status |
|---|---|---|---|
| Westward Beach Road Repair Project | 2022-10-20 | capital | design |
"""
        records = extract_project_records(text, source="civic-doc")
        self.assertEqual(len(records), 3)
        self.assertEqual(
            {record.canonical_name for record in records},
            {
                "CIVIC CENTER WATER TREATMENT FACILITY PHASE 2",
                "PERMANENT SKATE PARK",
                "WESTWARD BEACH ROAD REPAIR PROJECT",
            },
        )

    def test_literal_records_are_supported(self) -> None:
        text = """[
          {"project": "PCH Median Improvements Project", "date": "2022-09-01", "type": "capital", "status": "design"},
          {"project": "PCH Signal Synchronization System Improvements Project", "date": "2022-08-01", "type": "capital", "status": "completed"}
        ]"""
        records = extract_project_records(text, source="literal")
        self.assertEqual(len(records), 2)

    def test_temporal_semantics_use_latest_record_not_future_record(self) -> None:
        records = [
            ProjectRecord("Alpha Project", date(2022, 5, 1), "capital", "design", "a", 0),
            ProjectRecord("Alpha Project", date(2023, 2, 1), "capital", "completed", "b", 1),
            ProjectRecord("Beta Project", date(2022, 6, 1), "capital", "not started", "a", 2),
        ]
        latest = latest_records_on_or_before(records, date(2023, 1, 1))
        self.assertEqual(latest["ALPHA PROJECT"].status, "design")
        self.assertEqual(latest["ALPHA PROJECT"].report_date, date(2022, 5, 1))

    def test_funding_extraction_and_accumulation(self) -> None:
        funding_text = """
| Project | Date | Amount |
|---|---|---|
| Alpha Project | 2022-02-01 | $300,000 |
| Alpha Project | 2022-12-01 | 250K |
| Alpha Project | 2023-02-01 | $900,000 |
| Beta Project | 2022-04-01 | $700,000 |
"""
        entries = extract_funding_entries(funding_text, source="funding-db")
        self.assertEqual(len(entries), 4)
        self.assertEqual(parse_amount("$1.25M + $250K"), 1_500_000.0)

        records = [
            ProjectRecord("Alpha Project", date(2022, 12, 15), "capital", "design", "report", 0),
            ProjectRecord("Beta Project", date(2022, 12, 20), "disaster", "design", "report", 1),
        ]
        selected = select_projects(
            records,
            entries,
            cutoff=date(2023, 1, 1),
            project_type="capital",
            status="design",
            minimum_funding=500_000,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].canonical_name, "ALPHA PROJECT")
        self.assertEqual(selected[0].accumulated_funding, 550_000.0)
        self.assertEqual(selected[0].funding_sources, ("funding-db",))

    def test_strict_greater_than_threshold(self) -> None:
        records = [
            ProjectRecord("Exact Threshold", date(2022, 1, 1), "capital", "design")
        ]
        funding = [
            FundingEntry("Exact Threshold", date(2022, 1, 1), 500_000.0)
        ]
        selected = select_projects(
            records,
            funding,
            cutoff=date(2023, 1, 1),
            project_type="capital",
            status="design",
            minimum_funding=500_000,
        )
        self.assertEqual(selected, ())


if __name__ == "__main__":
    unittest.main()
