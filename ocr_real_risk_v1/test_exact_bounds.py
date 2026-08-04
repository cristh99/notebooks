from __future__ import annotations

import unittest

from .exact_bounds import (
    binomial_cdf,
    clopper_pearson_lower,
    clopper_pearson_upper,
)


class ExactBoundsTests(unittest.TestCase):
    def test_sparse_coverage_lower_bound_remains_near_zero(self) -> None:
        lower = clopper_pearson_lower(1, 1000, 0.0125)
        self.assertGreater(lower, 0.0)
        self.assertLess(lower, 0.001)

    def test_zero_event_upper_bound_uses_exact_closed_form(self) -> None:
        alpha = 0.025
        observed = clopper_pearson_upper(0, 100, alpha)
        expected = 1.0 - alpha ** (1.0 / 100)
        self.assertAlmostEqual(observed, expected, places=14)

    def test_binomial_cdf_is_monotone_in_probability(self) -> None:
        values = [binomial_cdf(10, 100, p) for p in (0.05, 0.1, 0.2)]
        self.assertGreater(values[0], values[1])
        self.assertGreater(values[1], values[2])

    def test_complementary_bounds_are_ordered(self) -> None:
        lower = clopper_pearson_lower(20, 100, 0.025)
        upper = clopper_pearson_upper(20, 100, 0.025)
        self.assertLess(lower, 0.2)
        self.assertGreater(upper, 0.2)
        self.assertLess(lower, upper)


if __name__ == "__main__":
    unittest.main()
