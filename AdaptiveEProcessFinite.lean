import Std

namespace AdaptiveEProcessFinite

/-- Branchwise continuation bounds compose after clearing denominators. -/
theorem branchwise_terms_preserve_bound
    (first0 first1 second0 second1 bound : Nat)
    (h0 : second0 ≤ first0)
    (h1 : second1 ≤ first1)
    (hfirst : first0 + first1 ≤ bound) :
    second0 + second1 ≤ bound := by
  exact Nat.le_trans (Nat.add_le_add h0 h1) hfirst

/-- Threshold crossing control follows by transitivity. -/
theorem threshold_crossing_transitive
    (thresholdTimesCrossing expectation bound : Nat)
    (hcross : thresholdTimesCrossing ≤ expectation)
    (hexpectation : expectation ≤ bound) :
    thresholdTimesCrossing ≤ bound := by
  exact Nat.le_trans hcross hexpectation

theorem factor_A_null_a_scaled : 3 * 0 + 1 * 3 = 3 := by decide
theorem factor_A_null_b_scaled : 2 * 0 + 1 * 3 = 3 := by decide
theorem factor_A_alt_b_scaled : 1 * 0 + 2 * 3 = 6 := by decide
theorem exact_optional_stopping_scaled : 9 * 1 = 9 := by decide
theorem posthoc_maximum_inflates_scaled : 4 < 5 := by decide

#print axioms AdaptiveEProcessFinite.branchwise_terms_preserve_bound
#print axioms AdaptiveEProcessFinite.threshold_crossing_transitive
#print axioms AdaptiveEProcessFinite.factor_A_null_a_scaled
#print axioms AdaptiveEProcessFinite.factor_A_null_b_scaled
#print axioms AdaptiveEProcessFinite.factor_A_alt_b_scaled
#print axioms AdaptiveEProcessFinite.exact_optional_stopping_scaled
#print axioms AdaptiveEProcessFinite.posthoc_maximum_inflates_scaled

end AdaptiveEProcessFinite
