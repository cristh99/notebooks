from __future__ import annotations

import unittest

from .numeric_context_v4 import (
    ContextStatus,
    EqualityConstraint,
    LinearConstraint,
    NumericField,
    evaluate_numeric_context,
    parse_decimal_token,
)


def field(field_id: str, value: str, source: str | None = None) -> NumericField:
    return NumericField(field_id=field_id, value=value, source_id=source or field_id)


class NumericContextV4Tests(unittest.TestCase):
    def test_page_008_claim_11246_is_conflict_from_two_independent_families(self) -> None:
        fields = [
            field("subtotal", "106.10"),
            field("gst", "6.37"),
            field("rounding", "-0.02"),
            field("total", "112.46", "ocr-total"),
            field("cash", "112.45", "ocr-cash"),
        ]
        constraints = [
            LinearConstraint(
                constraint_id="subtotal-plus-tax-plus-rounding",
                family="arithmetic",
                terms=(("subtotal", "1"), ("gst", "1"), ("rounding", "1"), ("total", "-1")),
                tolerance="0.001",
            ),
            EqualityConstraint(
                constraint_id="total-equals-cash",
                family="repeated_value",
                left_field_id="total",
                right_field_id="cash",
                tolerance="0.001",
            ),
        ]
        decision = evaluate_numeric_context("total", fields, constraints)
        self.assertEqual(decision.status, ContextStatus.CONFLICT)
        self.assertEqual(decision.failed_families, ("arithmetic", "repeated_value"))
        self.assertEqual(decision.passed_families, ())

    def test_corrected_total_is_consistent_but_module_never_auto_corrects(self) -> None:
        fields = [
            field("subtotal", "106.10"),
            field("gst", "6.37"),
            field("rounding", "-0.02"),
            field("total", "112.45", "candidate-total"),
            field("cash", "112.45", "cash-line"),
        ]
        constraints = [
            LinearConstraint(
                constraint_id="sum",
                family="arithmetic",
                terms=(("subtotal", "1"), ("gst", "1"), ("rounding", "1"), ("total", "-1")),
            ),
            EqualityConstraint(
                constraint_id="repeat",
                family="repeated_value",
                left_field_id="total",
                right_field_id="cash",
            ),
        ]
        decision = evaluate_numeric_context("total", fields, constraints)
        self.assertEqual(decision.status, ContextStatus.CONSISTENT)
        self.assertIsNone(decision.replacement_value)

    def test_one_available_family_is_insufficient(self) -> None:
        decision = evaluate_numeric_context(
            "total",
            [field("subtotal", "10.00"), field("total", "10.01")],
            [
                LinearConstraint(
                    constraint_id="sum",
                    family="arithmetic",
                    terms=(("subtotal", "1"), ("total", "-1")),
                )
            ],
        )
        self.assertEqual(decision.status, ContextStatus.INSUFFICIENT)
        self.assertEqual(decision.reason_code, "INSUFFICIENT_INDEPENDENT_FAMILIES")

    def test_mixed_pass_and_fail_is_insufficient_not_false_certainty(self) -> None:
        decision = evaluate_numeric_context(
            "total",
            [
                field("subtotal", "10.00"),
                field("total", "10.00"),
                field("cash", "10.01"),
            ],
            [
                LinearConstraint(
                    constraint_id="sum",
                    family="arithmetic",
                    terms=(("subtotal", "1"), ("total", "-1")),
                ),
                EqualityConstraint(
                    constraint_id="repeat",
                    family="repeated_value",
                    left_field_id="total",
                    right_field_id="cash",
                ),
            ],
        )
        self.assertEqual(decision.status, ContextStatus.INSUFFICIENT)
        self.assertEqual(decision.reason_code, "MIXED_CONTEXT_EVIDENCE")

    def test_missing_field_yields_unavailable_constraint(self) -> None:
        decision = evaluate_numeric_context(
            "total",
            [field("total", "10.00"), field("cash", "10.00")],
            [
                LinearConstraint(
                    constraint_id="sum",
                    family="arithmetic",
                    terms=(("subtotal", "1"), ("total", "-1")),
                ),
                EqualityConstraint(
                    constraint_id="repeat",
                    family="repeated_value",
                    left_field_id="total",
                    right_field_id="cash",
                ),
            ],
        )
        self.assertEqual(decision.status, ContextStatus.INSUFFICIENT)
        self.assertEqual(decision.available_constraints, 1)

    def test_duplicate_field_or_constraint_ids_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_numeric_context(
                "x",
                [field("x", "1.00", "a"), field("x", "1.00", "b")],
                [],
            )
        with self.assertRaises(ValueError):
            evaluate_numeric_context(
                "x",
                [field("x", "1.00"), field("y", "1.00")],
                [
                    EqualityConstraint("same", "repeat", "x", "y"),
                    EqualityConstraint("same", "repeat2", "x", "y"),
                ],
            )

    def test_decimal_parser_is_ascii_and_unambiguous(self) -> None:
        self.assertEqual(str(parse_decimal_token("HNL 1,234.50")), "1234.50")
        self.assertEqual(str(parse_decimal_token("(12.50)")), "-12.50")
        with self.assertRaises(ValueError):
            parse_decimal_token("1.234,50")
        with self.assertRaises(ValueError):
            parse_decimal_token("١٢.٥٠")

    def test_receipt_is_deterministic_under_field_and_constraint_order(self) -> None:
        fields = [field("x", "5.00"), field("y", "5.00"), field("z", "5.00")]
        constraints = [
            EqualityConstraint("xy", "repeat_a", "x", "y"),
            EqualityConstraint("xz", "repeat_b", "x", "z"),
        ]
        forward = evaluate_numeric_context("x", fields, constraints)
        reverse = evaluate_numeric_context("x", reversed(fields), reversed(constraints))
        self.assertEqual(forward, reverse)


if __name__ == "__main__":
    unittest.main()
