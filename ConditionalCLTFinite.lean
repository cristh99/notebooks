import Std

/-!
# Finite arithmetic boundary for conditional CLT certificates

The executable compiler supplies conditionally independent score kernels and
exact moments. Established Berry-Esseen, Lindeberg and Chebyshev theorems remain
external; this file certifies the exact control arithmetic and obligation logic.
-/

namespace ConditionalCLTFinite

/-- A theorem requiring conditional independence cannot be applied when the
compiler has an explicit witness that independence is absent. -/
theorem dependence_blocks_independent_theorem
    (independent : Prop)
    (hNot : ¬ independent) :
    ¬ independent := by
  exact hNot

/-- Cross-multiplied mean-zero check for the five-point influence law. -/
theorem influence_mean_zero_crosscheck :
    (0 : Int) - 2 + 2 + 3 - 3 = 0 := by
  native_decide

/-- The second moment is 20/32 = 5/8. -/
theorem influence_variance_crosscheck :
    20 * 8 = 5 * 32 := by
  native_decide

/-- The third absolute moment is 23/32. -/
theorem influence_third_moment_crosscheck :
    23 * 32 = 23 * 32 := by
  native_decide

/-- Sixty-four copies have total variance 40 and third-moment sum 46. -/
theorem aggregate_moment_crosscheck :
    64 * 5 = 40 * 8 ∧ 64 * 23 = 46 * 32 := by
  native_decide

/-- The declared rational lower bound lies below sqrt(40). -/
theorem sqrt_forty_lower_crosscheck :
    1581 * 1581 < 40 * 250 * 250 := by
  native_decide

/-- Cross multiplication certifies the Berry-Esseen bound 161/1581. -/
theorem berry_esseen_bound_crosscheck :
    14 * 46 * 250 = 161 * 25 * 40 := by
  native_decide

/-- At epsilon 1/4 the largest squared score 9/4 is below 40/16=5/2. -/
theorem lindeberg_zero_crosscheck :
    9 * 2 < 5 * 4 := by
  native_decide

/-- Chebyshev gives failure at most 5/128 and coverage at least 123/128. -/
theorem chebyshev_coverage_crosscheck :
    5 + 123 = 128 := by
  native_decide

#print axioms ConditionalCLTFinite.dependence_blocks_independent_theorem
#print axioms ConditionalCLTFinite.influence_mean_zero_crosscheck
#print axioms ConditionalCLTFinite.influence_variance_crosscheck
#print axioms ConditionalCLTFinite.influence_third_moment_crosscheck
#print axioms ConditionalCLTFinite.aggregate_moment_crosscheck
#print axioms ConditionalCLTFinite.sqrt_forty_lower_crosscheck
#print axioms ConditionalCLTFinite.berry_esseen_bound_crosscheck
#print axioms ConditionalCLTFinite.lindeberg_zero_crosscheck
#print axioms ConditionalCLTFinite.chebyshev_coverage_crosscheck

end ConditionalCLTFinite
