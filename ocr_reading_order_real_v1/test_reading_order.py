from __future__ import annotations

import json
import unittest

from .core import (
    Block,
    CANDIDATES,
    Page,
    canonical_json,
    order_metrics,
    sha256_bytes,
    solver_receipt,
    split_name,
)
from .verify_report import stable_payload


def block(identifier: str, order: int, box: tuple[float, float, float, float]) -> Block:
    return Block(identifier, order, "text_block", box)


class ReadingOrderTests(unittest.TestCase):
    def test_two_columns_with_header_and_footer(self) -> None:
        page = Page(
            "two-columns",
            1000,
            1400,
            "double_column",
            "academic_literature",
            "english",
            (
                block("header", 0, (50, 20, 950, 100)),
                block("left-1", 1, (60, 160, 460, 320)),
                block("left-2", 2, (60, 350, 460, 520)),
                block("right-1", 3, (540, 160, 940, 320)),
                block("right-2", 4, (540, 350, 940, 520)),
                block("footer", 5, (50, 1250, 950, 1320)),
            ),
        )
        candidate = next(item for item in CANDIDATES if item.name == "xycut_loose")
        predicted = candidate.orderer(page.blocks, page.width, page.height)
        self.assertEqual([item.order for item in predicted], list(range(6)))
        self.assertEqual(order_metrics(page, predicted)["read_order_edit"], 0.0)

    def test_yx_interleaves_columns(self) -> None:
        page = Page(
            "columns-no-header",
            1000,
            1200,
            "double_column",
            "book",
            "english",
            (
                block("left-1", 0, (50, 100, 450, 220)),
                block("left-2", 1, (50, 260, 450, 380)),
                block("right-1", 2, (550, 100, 950, 220)),
                block("right-2", 3, (550, 260, 950, 380)),
            ),
        )
        baseline = next(item for item in CANDIDATES if item.name == "yx_baseline")
        xycut = next(item for item in CANDIDATES if item.name == "xycut_balanced")
        baseline_metric = order_metrics(page, baseline.orderer(page.blocks, page.width, page.height))
        xycut_metric = order_metrics(page, xycut.orderer(page.blocks, page.width, page.height))
        self.assertGreater(baseline_metric["read_order_edit"], 0.0)
        self.assertEqual(xycut_metric["read_order_edit"], 0.0)

    def test_metrics_reject_non_permutation(self) -> None:
        page = Page(
            "bad",
            100,
            100,
            "single_column",
            "book",
            "english",
            (block("a", 0, (0, 0, 10, 10)), block("b", 1, (0, 20, 10, 30))),
        )
        with self.assertRaises(ValueError):
            order_metrics(page, [page.blocks[0], page.blocks[0]])

    def test_split_is_stable(self) -> None:
        value = split_name("images/example.png")
        self.assertEqual(value, split_name("images/example.png"))
        self.assertIn(value, {"development", "holdout"})

    def test_solver_receipt_selects_geometry_canary(self) -> None:
        receipt = solver_receipt()
        self.assertEqual(receipt["selected_experiment"], "geometry_only_order_canary")
        payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        self.assertEqual(
            receipt["receipt_sha256"],
            sha256_bytes(canonical_json(payload).encode("utf-8")),
        )

    def test_stable_payload_excludes_runtime(self) -> None:
        report = {
            "schema": "x",
            "stable_payload_sha256": "ignored",
            "runtime": {"seconds": 1},
            "environment": {"python": "x"},
        }
        self.assertEqual(stable_payload(report), {"schema": "x"})

    def test_semantic_tamper_changes_canonical_payload(self) -> None:
        original = {"schema": "x", "holdout": {"edit": 0.1}}
        tampered = json.loads(json.dumps(original))
        tampered["holdout"]["edit"] = 0.0
        self.assertNotEqual(canonical_json(original), canonical_json(tampered))


if __name__ == "__main__":
    unittest.main()
