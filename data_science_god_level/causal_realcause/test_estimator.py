from __future__ import annotations

import unittest

import numpy as np

from estimator import estimate_causal_effect


class EstimatorTests(unittest.TestCase):
    def test_recovers_nonlinear_constant_effect(self) -> None:
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

    def test_handles_binary_outcome(self) -> None:
        rng = np.random.default_rng(11)
        n = 2500
        x = rng.normal(size=(n, 6))
        propensity = 1.0 / (1.0 + np.exp(-(0.5 * x[:, 0] - 0.4 * x[:, 1])))
        a = rng.binomial(1, propensity)
        p = 1.0 / (1.0 + np.exp(-(-0.8 + 0.4 * x[:, 0] + 0.6 * a)))
        y = rng.binomial(1, p)
        result = estimate_causal_effect(x, a, y, random_state=13)
        self.assertTrue(result.diagnostics["finite"])
        self.assertTrue(np.isfinite(result.ate))
        self.assertLess(result.ate_ci_lower, result.ate_ci_upper)

    def test_rejects_nonbinary_treatment(self) -> None:
        with self.assertRaises(ValueError):
            estimate_causal_effect(np.zeros((200, 2)), np.arange(200) % 3, np.zeros(200))


if __name__ == "__main__":
    unittest.main()
