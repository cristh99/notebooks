from __future__ import annotations

from pathlib import Path


CANDIDATE = Path(
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py"
)
TEST = Path(
    "ocr_real_risk_v1/test_numeric_consensus_candidate_v4_wildreceipt.py"
)


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one target, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    replace_once(
        CANDIDATE,
        '''"""Freeze numeric-consensus-v4 for untouched WildReceipt validation.

The source corpus was sealed before v4 development. This candidate binds the
selected detector, byte-frozen digit forest, crop guard, one-unit-per-receipt
adapter, exact gates, runtime, and source bytes before any Parquet row is read.
"""''',
        '''"""Freeze numeric-consensus-v4 after geometry discovery but before OCR.

The immutable WildReceipt objects were reserved before v4 development. A later
manifest-only attempt revealed that the mirror uses LayoutLM-normalized boxes;
no OCR binary or candidate inference ran. This candidate binds the corrected
projection, detector, byte-frozen forest, guard, risk unit, exact gates, and
runtime before any OCR outcome is generated.
"""''',
        "candidate chronology",
    )
    replace_once(
        CANDIDATE,
        '''        "power_plan": {
            "published_receipt_rows_from_hub_metadata": 1739,
            "development_selected": 993,
            "development_accepted": 319,
            "development_baseline_errors": 46,
            "projected_selected_for_10x_if_rates_hold": 1889,
            "underpower_is_an_allowed_terminal_result": True,
            "planning_only_not_a_certificate": True,
        },''',
        '''        "power_plan": {
            "published_receipt_rows_from_hub_metadata": 1739,
            "maximum_possible_selected_unique_receipts": 1739,
            "minimum_selected_unique_receipts": 1200,
            "minimum_selection_yield_required": 0.6900517538815412,
            "development_selected": 993,
            "development_accepted": 319,
            "development_acceptance_rate": 0.32124874118831825,
            "minimum_selected_for_projected_400_accepts": 1246,
            "minimum_selection_yield_for_projected_400_accepts": (
                0.7165037377803335
            ),
            "finite_population_feasibility": True,
            "underpower_is_an_allowed_terminal_result": True,
            "planning_only_not_a_certificate": True,
        },''',
        "candidate power plan",
    )
    replace_once(
        TEST,
        '''        self.assertTrue(
            protocol["power_plan"]["underpower_is_an_allowed_terminal_result"]
        )''',
        '''        power = protocol["power_plan"]
        self.assertEqual(power["maximum_possible_selected_unique_receipts"], 1739)
        self.assertEqual(power["minimum_selected_unique_receipts"], 1200)
        self.assertEqual(power["minimum_selected_for_projected_400_accepts"], 1246)
        self.assertLessEqual(
            power["minimum_selected_for_projected_400_accepts"],
            power["maximum_possible_selected_unique_receipts"],
        )
        self.assertTrue(power["finite_population_feasibility"])
        self.assertTrue(power["underpower_is_an_allowed_terminal_result"])''',
        "candidate power test",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
