from __future__ import annotations

import unittest

from ocr_reading_order_real_v1.core import Block
from .router import _strong_body_columns, route


def item(block_id: str, bbox: tuple[float, float, float, float]):
    return {"block_id": block_id, "bbox": list(bbox)}


def geometry(block_id: str, bbox: tuple[float, float, float, float]) -> Block:
    return Block(block_id, 0, "test", bbox)


class ContextRouterTests(unittest.TestCase):
    def test_identical_candidates_keep_baseline(self) -> None:
        blocks = [item("A", (0, 0, 100, 20)), item("B", (0, 40, 100, 60))]
        decision = route(blocks, 100, 100)
        self.assertEqual(decision.selected, "baseline")
        self.assertEqual(decision.reason, "CANDIDATES_IDENTICAL")

    def test_header_disagreement_protects_baseline(self) -> None:
        blocks = [
            item("L1", (0, 5, 40, 15)),
            item("R1", (60, 5, 100, 15)),
            item("L2", (0, 22, 40, 32)),
            item("R2", (60, 22, 100, 32)),
            item("BODY", (0, 45, 100, 90)),
        ]
        decision = route(blocks, 100, 100)
        self.assertEqual(decision.selected, "baseline")
        self.assertEqual(decision.reason, "HEADER_METADATA_PROTECTION")

    def test_footer_disagreement_selects_geometry(self) -> None:
        blocks = [
            item("BODY", (0, 0, 100, 50)),
            item("L1", (0, 65, 40, 75)),
            item("R1", (60, 65, 100, 75)),
            item("L2", (0, 82, 40, 92)),
            item("R2", (60, 82, 100, 92)),
        ]
        decision = route(blocks, 100, 100)
        self.assertEqual(decision.selected, "geometry")
        self.assertEqual(decision.reason, "LOWER_PARALLEL_REGION")

    def test_strong_body_columns_select_geometry(self) -> None:
        blocks = [
            item("L1", (0, 40, 40, 50)),
            item("R1", (60, 40, 100, 50)),
            item("L2", (0, 60, 40, 70)),
            item("R2", (60, 60, 100, 70)),
        ]
        decision = route(blocks, 100, 100)
        self.assertEqual(decision.selected, "geometry")
        self.assertEqual(decision.reason, "STRONG_BODY_COLUMNS")

    def test_spanning_body_block_blocks_column_evidence(self) -> None:
        changed = [
            geometry("L1", (0, 40, 40, 50)),
            geometry("R1", (60, 40, 100, 50)),
            geometry("L2", (0, 60, 40, 70)),
            geometry("R2", (60, 60, 100, 70)),
        ]
        all_blocks = [*changed, geometry("SPAN", (0, 45, 100, 65))]
        evidence = _strong_body_columns(changed, all_blocks, 100, 100)
        self.assertFalse(evidence["strong"])
        self.assertTrue(evidence["spanning_block_present"])

    def test_selected_order_is_permutation(self) -> None:
        blocks = [
            item("A", (0, 60, 40, 70)),
            item("B", (60, 60, 100, 70)),
            item("C", (0, 80, 40, 90)),
            item("D", (60, 80, 100, 90)),
        ]
        decision = route(blocks, 100, 100)
        self.assertEqual(set(decision.selected_order), {"A", "B", "C", "D"})
        self.assertEqual(len(decision.selected_order), 4)


if __name__ == "__main__":
    unittest.main()
