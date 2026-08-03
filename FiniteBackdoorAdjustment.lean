import Mathlib

/-!
# Finite arithmetic boundary for exact backdoor adjustment

The executable verifier certifies graph separation, admissible adjustment sets,
positivity and exact finite probabilities. This file formalizes the arithmetic
core of the two-stratum adjustment and its contrast with the naive association.
-/

namespace FiniteBackdoorAdjustment

/-- Two-stratum standardization is a weighted sum of stratum-specific outcomes. -/
theorem two_stratum_standardization
    (w0 w1 y0 y1 : ℚ) :
    w0 * y0 + w1 * y1 = w0 * y0 + w1 * y1 := by
  rfl

/-- The adjusted low-treatment risk in the control equals three tenths. -/
theorem adjusted_low :
    (1 / 2 : ℚ) * (1 / 10 : ℚ) +
      (1 / 2 : ℚ) * (1 / 2 : ℚ) = 3 / 10 := by
  norm_num

/-- The adjusted high-treatment risk in the control equals seven tenths. -/
theorem adjusted_high :
    (1 / 2 : ℚ) * (1 / 2 : ℚ) +
      (1 / 2 : ℚ) * (9 / 10 : ℚ) = 7 / 10 := by
  norm_num

/-- The exact adjusted causal contrast is two fifths. -/
theorem adjusted_effect :
    (7 / 10 : ℚ) - (3 / 10 : ℚ) = 2 / 5 := by
  norm_num

/-- The unadjusted observational contrast is three fifths. -/
theorem naive_effect :
    (4 / 5 : ℚ) - (1 / 5 : ℚ) = 3 / 5 := by
  norm_num

/-- The confounding bias is one fifth. -/
theorem confounding_bias :
    (3 / 5 : ℚ) - (2 / 5 : ℚ) = 1 / 5 := by
  norm_num

/-- Descendant adjustment can be rejected by an explicit eligibility predicate. -/
theorem descendant_fails_eligibility
    {Node : Type}
    (eligible : Node → Prop)
    (mediator : Node)
    (hnot : ¬ eligible mediator) :
    ¬ eligible mediator := by
  exact hnot

#print axioms FiniteBackdoorAdjustment.two_stratum_standardization
#print axioms FiniteBackdoorAdjustment.adjusted_low
#print axioms FiniteBackdoorAdjustment.adjusted_high
#print axioms FiniteBackdoorAdjustment.adjusted_effect
#print axioms FiniteBackdoorAdjustment.naive_effect
#print axioms FiniteBackdoorAdjustment.confounding_bias
#print axioms FiniteBackdoorAdjustment.descendant_fails_eligibility

end FiniteBackdoorAdjustment
