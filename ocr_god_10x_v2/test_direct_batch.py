from __future__ import annotations

import unittest

import numpy as np

from .direct_batch import direct_gate, order_points, perspective_crop, polygon_sort_key


class DirectBatchTests(unittest.TestCase):
    def test_order_points_normalizes_quad(self) -> None:
        poly = [[100, 80], [10, 10], [10, 80], [100, 10]]
        ordered = order_points(poly)
        self.assertTrue(np.allclose(ordered[0], [10, 10]))
        self.assertTrue(np.allclose(ordered[1], [100, 10]))
        self.assertTrue(np.allclose(ordered[2], [100, 80]))
        self.assertTrue(np.allclose(ordered[3], [10, 80]))

    def test_perspective_crop_is_nonempty(self) -> None:
        image = np.full((100, 200, 3), 255, dtype=np.uint8)
        image[20:60, 30:170] = 0
        crop = perspective_crop(image, [[30, 20], [170, 20], [170, 60], [30, 60]])
        self.assertGreater(crop.shape[0], 1)
        self.assertGreater(crop.shape[1], 1)
        self.assertLess(float(crop.mean()), 255.0)

    def test_polygon_sort_key_prefers_top_then_left(self) -> None:
        top_right = [[100, 10], [150, 10], [150, 30], [100, 30]]
        bottom_left = [[0, 50], [50, 50], [50, 70], [0, 70]]
        self.assertLess(polygon_sort_key(top_right), polygon_sort_key(bottom_left))

    def test_direct_gate_requires_speed_and_quality(self) -> None:
        baseline = {
            "total_wall_seconds": 100.0,
            "total_cpu_seconds": 100.0,
            "word_micro": {"error": 0.2, "f1": 0.8},
            "numeric_micro": {"error": 0.1, "f1": 0.9},
            "catastrophic_pages": 0,
        }
        fast_bad = {
            "total_wall_seconds": 5.0,
            "total_cpu_seconds": 5.0,
            "word_micro": {"error": 0.19, "f1": 0.81},
            "numeric_micro": {"error": 0.09, "f1": 0.91},
            "catastrophic_pages": 0,
        }
        gate = direct_gate(baseline, fast_bad)
        self.assertTrue(gate["wall_speed_10x"])
        self.assertFalse(gate["full_10x_gate"])


if __name__ == "__main__":
    unittest.main()
