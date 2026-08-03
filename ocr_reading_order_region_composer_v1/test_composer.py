from __future__ import annotations

import unittest

from .composer import compose, compose_with_parameters
from .development_replay import candidate_specs, selection_key


def item(block_id: str, bbox: tuple[float, float, float, float]):
    return {"block_id": block_id, "bbox": list(bbox)}


class RegionComposerTests(unittest.TestCase):
    def test_header_is_preserved_row_major(self) -> None:
        blocks = [
            item("H1", (0, 5, 40, 15)),
            item("H2", (60, 5, 100, 15)),
            item("L1", (0, 40, 40, 50)),
            item("R1", (60, 40, 100, 50)),
            item("L2", (0, 60, 40, 70)),
            item("R2", (60, 60, 100, 70)),
        ]
        decision = compose(blocks, 100, 100)
        self.assertEqual(decision.top_order, ("H1", "H2"))
        self.assertEqual(decision.order[:2], ("H1", "H2"))

    def test_middle_columns_are_composed_locally(self) -> None:
        blocks = [
            item("HEADER", (0, 0, 100, 20)),
            item("L1", (0, 40, 40, 50)),
            item("R1", (60, 40, 100, 50)),
            item("L2", (0, 55, 40, 62)),
            item("R2", (60, 55, 100, 62)),
            item("FOOTER", (0, 80, 100, 90)),
        ]
        decision = compose(blocks, 100, 100)
        self.assertEqual(decision.order, ("HEADER", "L1", "L2", "R1", "R2", "FOOTER"))

    def test_lower_band_is_independent(self) -> None:
        blocks = [
            item("BODY", (0, 35, 100, 55)),
            item("LL1", (0, 70, 40, 78)),
            item("RR1", (60, 70, 100, 78)),
            item("LL2", (0, 85, 40, 93)),
            item("RR2", (60, 85, 100, 93)),
        ]
        decision = compose(blocks, 100, 100)
        self.assertEqual(decision.lower_order, ("LL1", "LL2", "RR1", "RR2"))
        self.assertEqual(decision.order[0], "BODY")

    def test_output_is_permutation(self) -> None:
        blocks = [
            item("A", (0, 0, 20, 10)),
            item("B", (30, 20, 50, 30)),
            item("C", (60, 40, 80, 50)),
        ]
        decision = compose(blocks, 100, 100)
        self.assertEqual(set(decision.order), {"A", "B", "C"})
        self.assertEqual(len(decision.order), 3)

    def test_invalid_thresholds_fail_closed(self) -> None:
        blocks = [item("A", (0, 0, 20, 10)), item("B", (0, 20, 20, 30))]
        with self.assertRaises(ValueError):
            compose_with_parameters(
                blocks,
                100,
                100,
                header_fraction=0.70,
                lower_split=0.60,
            )

    def test_candidate_family_is_fixed(self) -> None:
        specs = candidate_specs()
        self.assertEqual(len(specs), 13)
        self.assertEqual(specs[0]["name"], "baseline")
        self.assertIn("band_30_65", {specification["name"] for specification in specs})

    def test_selection_prefers_conservative_header_on_exact_tie(self) -> None:
        summary = {
            "weighted_constraint_accuracy": 1.0,
            "exact_partial_order_rate": 1.0,
            "mean_canonical_read_order_edit": 0.1,
        }
        less_protected = {"name": "band_25_65", "header_fraction": 0.25, "lower_split": 0.65}
        more_protected = {"name": "band_30_65", "header_fraction": 0.30, "lower_split": 0.65}
        self.assertLess(selection_key(more_protected, summary), selection_key(less_protected, summary))


if __name__ == "__main__":
    unittest.main()
