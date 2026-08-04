from __future__ import annotations

import unittest

import numpy as np

from estimator import estimate_causal_effect


class EstimatorTests(unittest.TestCase):
    def test_cross_fitted_aipw_recovers_constant_effect(self) -> None:
        rng = np.random.default_rng(20260804)
        n = 3000
        x = rng.normal(size=(n, 8))
        logits = 0.7 * x[:, 0] - 0.5 * x[:, 1] + 0.25 * x[:, 2] * x[:, 3]
        propensity = 1.0 / (1.0 + np.exp(-logits))
        a = rng.binomial(1, propensity)
        baseline = 1.5 * x[:, 0] + 0.8 * np.square(x[:, 1]) - x[:, 2] * x[:, 3]
        effect = 2.0
        y = baseline + effect * a + rng.normal(scale=1.0, size=n)
        result = estimate_causal_effect(x, a, y, random_state=7)
        self.assertLess(abs(result.ate - effect), 0.20)
        self.assertLess(abs(result.att - effect), 0.25)
        self.assertTrue(result.diagnostics["finite"])
        self.assertEqual(result.ite.shape, (n,))

    def test_rejects_nonbinary_treatment(self) -> None:
        x = np.zeros((200, 2))
        a = np.arange(200) % 3
        y = np.zeros(200)
        with self.assertRaises(ValueError):
            estimate_causal_effect(x, a, y)


if __name__ == "__main__":
    unittest.main()
