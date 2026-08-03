import Mathlib

/-!
# Finite algebraic boundary for predictable adaptive e-processes

This file formalizes the elementary inequalities used by the exact finite
compiler. The full measure-theoretic supermartingale theorem remains outside
this file.
-/

namespace AdaptiveEProcessFinite

/-- Branch-specific conditional factors with mean at most one preserve a first-step mean bound. -/
theorem branchwise_conditional_factors_preserve_mean
    (p0 p1 f0 f1 c0 c1 : ℝ)
    (hp0 : 0 ≤ p0) (hp1 : 0 ≤ p1)
    (hf0 : 0 ≤ f0) (hf1 : 0 ≤ f1)
    (hfirst : p0 * f0 + p1 * f1 ≤ 1)
    (hc0 : c0 ≤ 1) (hc1 : c1 ≤ 1) :
    p0 * f0 * c0 + p1 * f1 * c1 ≤ 1 := by
  have h0 : p0 * f0 * c0 ≤ p0 * f0 := by
    exact mul_le_of_le_one_right (mul_nonneg hp0 hf0) hc0
  have h1 : p1 * f1 * c1 ≤ p1 * f1 := by
    exact mul_le_of_le_one_right (mul_nonneg hp1 hf1) hc1
  linarith

/-- The exact factor A is valid for the first null world. -/
theorem factor_A_null_a :
    (3 / 4 : ℝ) * 0 + (1 / 4 : ℝ) * 3 = 3 / 4 := by
  norm_num

/-- The exact factor A is tight for the second null world. -/
theorem factor_A_null_b :
    (2 / 3 : ℝ) * 0 + (1 / 3 : ℝ) * 3 = 1 := by
  norm_num

/-- The worst alternative expectation of factor A equals two. -/
theorem factor_A_alt_b :
    (1 / 3 : ℝ) * 0 + (2 / 3 : ℝ) * 3 = 2 := by
  norm_num

/-- Markov/Ville arithmetic: a threshold crossing bound follows from the mean bound. -/
theorem threshold_crossing_bound
    (threshold crossing expectation : ℝ)
    (hthreshold : 0 < threshold)
    (hcross : threshold * crossing ≤ expectation)
    (hexpectation : expectation ≤ 1) :
    crossing ≤ 1 / threshold := by
  apply (le_div_iff₀ hthreshold).2
  nlinarith [hcross, hexpectation]

/-- In the tight null world the exact threshold-nine crossing probability is one ninth. -/
theorem exact_optional_stopping_demo :
    (9 : ℝ) * (1 / 9 : ℝ) = 1 := by
  norm_num

/-- Post-hoc maximization of two individually valid factors has null mean five fourths. -/
theorem posthoc_maximum_inflates :
    (1 / 4 : ℝ) * (1 / 2 : ℝ) +
      (3 / 4 : ℝ) * (3 / 2 : ℝ) = 5 / 4 := by
  norm_num

#print axioms AdaptiveEProcessFinite.branchwise_conditional_factors_preserve_mean
#print axioms AdaptiveEProcessFinite.factor_A_null_a
#print axioms AdaptiveEProcessFinite.factor_A_null_b
#print axioms AdaptiveEProcessFinite.factor_A_alt_b
#print axioms AdaptiveEProcessFinite.threshold_crossing_bound
#print axioms AdaptiveEProcessFinite.exact_optional_stopping_demo
#print axioms AdaptiveEProcessFinite.posthoc_maximum_inflates

end AdaptiveEProcessFinite
