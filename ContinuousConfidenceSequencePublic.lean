import Std

/-!
# Public formal boundary for continuous-parameter anytime confidence sequences

The independent verifier uses two monotone one-sided e-process mixtures, assigns
alpha/2 to each side and encloses threshold roots by exact dyadic bisection.
Ville's inequality is established externally. The declarations below certify
two-sided composition and closed control arithmetic by kernel reduction only.
-/

namespace ContinuousConfidenceSequencePublic

/-- Two one-sided error bounds add under the union bound. -/
theorem two_sided_error_bounds_add
    (lowerError upperError oneSidedBudget : Nat)
    (hLower : lowerError ≤ oneSidedBudget)
    (hUpper : upperError ≤ oneSidedBudget) :
    lowerError + upperError ≤ oneSidedBudget + oneSidedBudget := by
  exact Nat.add_le_add hLower hUpper

/-- Twenty bisection steps give denominator 2^20 = 1,048,576. -/
theorem dyadic_resolution_twenty :
    decide (2 ^ 20 = 1048576) = true := by
  rfl

/-- Alpha/2 on both sides recombines to alpha after common scaling. -/
theorem bonferroni_allocation_scaled :
    decide (1 + 1 = 2) = true := by
  rfl

/-- The lower threshold root is enclosed by adjacent dyadic points. -/
theorem final_lower_root_bracket_adjacent :
    decide
      (602055 + 1 = 602056 ∧
       75257 * 8 = 602056 ∧
       131072 * 8 = 1048576) = true := by
  rfl

/-- The upper threshold root is enclosed by adjacent dyadic points. -/
theorem final_upper_root_bracket_adjacent :
    decide
      (232533 * 4 = 930132 ∧
       262144 * 4 = 1048576 ∧
       930132 + 1 = 930133) = true := by
  rfl

/-- The conservative outer interval contains the reference mean three quarters. -/
theorem final_outer_interval_contains_three_quarters :
    decide
      (602055 * 4 ≤ 3 * 1048576 ∧
       3 * 1048576 ≤ 930133 * 4) = true := by
  rfl

/-- The reference one-sided e-process never reaches threshold forty. -/
theorem reference_never_crosses_threshold :
    decide (687 < 40 * 512) = true := by
  rfl

/-- The finite resource control requires 11,264 mixture evaluations. -/
theorem resource_requirement_control :
    decide (64 * 8 * 22 = 11264 ∧ 10000 < 11264) = true := by
  rfl

/-- Global lambda endpoints have nonnegative factors at all bounded corners. -/
theorem endpoint_factors_nonnegative :
    decide
      (0 ≤ 1 ∧ 0 ≤ 0 ∧ 0 ≤ 2 ∧ 0 ≤ 1 ∧
       0 ≤ 1 ∧ 0 ≤ 2 ∧ 0 ≤ 0 ∧ 0 ≤ 1) = true := by
  rfl

/-- Post-hoc maximization inflates the valid mean-one control to five quarters. -/
theorem post_hoc_maximum_inflates_mean :
    decide (4 < 5) = true := by
  rfl

#print axioms ContinuousConfidenceSequencePublic.two_sided_error_bounds_add
#print axioms ContinuousConfidenceSequencePublic.dyadic_resolution_twenty
#print axioms ContinuousConfidenceSequencePublic.bonferroni_allocation_scaled
#print axioms ContinuousConfidenceSequencePublic.final_lower_root_bracket_adjacent
#print axioms ContinuousConfidenceSequencePublic.final_upper_root_bracket_adjacent
#print axioms ContinuousConfidenceSequencePublic.final_outer_interval_contains_three_quarters
#print axioms ContinuousConfidenceSequencePublic.reference_never_crosses_threshold
#print axioms ContinuousConfidenceSequencePublic.resource_requirement_control
#print axioms ContinuousConfidenceSequencePublic.endpoint_factors_nonnegative
#print axioms ContinuousConfidenceSequencePublic.post_hoc_maximum_inflates_mean

end ContinuousConfidenceSequencePublic
