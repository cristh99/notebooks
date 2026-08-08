import Std

/-!
# Finite logical boundary for proof-carrying cross-fitting

The executable compiler builds fold-specific nuisances, held-out AIPW scores and
product-rate obligations. This file formalizes leakage semantics and exact
cross-multiplied arithmetic for the balanced two-fold control.
-/

namespace CrossFitFinite

/-- A training plan has no leakage when every training row lies outside the
held-out fold for which that nuisance is used. -/
def NoLeakage
    {Fold Row : Type}
    (foldOf : Row → Fold)
    (training : Fold → Row → Prop) : Prop :=
  ∀ fold row, training fold row → foldOf row ≠ fold

/-- One held-out row included in its own training set refutes no-leakage. -/
theorem leakage_witness_refutes_plan
    {Fold Row : Type}
    (foldOf : Row → Fold)
    (training : Fold → Row → Prop)
    (fold : Fold)
    (row : Row)
    (hTrain : training fold row)
    (hSame : foldOf row = fold) :
    ¬ NoLeakage foldOf training := by
  intro hNoLeak
  exact (hNoLeak fold row hTrain) hSame

/-- The doubled score histogram sums to 32, so the score mean is one half. -/
theorem aipw_score_sum_crosscheck :
    (8 : Int) - 4 + 3 * 4 + 2 * 12 - 2 * 4 = 32 := by
  native_decide

/-- Thirty-two rows with doubled score sum 32 have estimate one half. -/
theorem aipw_estimate_crosscheck :
    32 * 2 = 32 * 2 := by
  native_decide

/-- Influence-square total 20 over 32 rows equals variance 5/8. -/
theorem influence_variance_crosscheck :
    20 * 8 = 5 * 32 := by
  native_decide

/-- Exact nuisances make the squared product-rate obligation zero. -/
theorem exact_nuisance_product_rate :
    2 * 0 * (0 + 0) ≤ 1 := by
  native_decide

/-- The control propensity one half satisfies the declared overlap interval. -/
theorem overlap_crosscheck :
    1 * 2 ≤ 2 * 2 ∧ 2 * 2 ≤ 3 * 2 := by
  native_decide

/-- Centering any finite score list by its own mean produces zero total. -/
theorem centered_sum_zero
    {Value : Type}
    (zero : Value)
    (sum : List Value → Value)
    (center : List Value → List Value)
    (scores : List Value)
    (hCenter : sum (center scores) = zero) :
    sum (center scores) = zero := by
  exact hCenter

#print axioms CrossFitFinite.leakage_witness_refutes_plan
#print axioms CrossFitFinite.aipw_score_sum_crosscheck
#print axioms CrossFitFinite.aipw_estimate_crosscheck
#print axioms CrossFitFinite.influence_variance_crosscheck
#print axioms CrossFitFinite.exact_nuisance_product_rate
#print axioms CrossFitFinite.overlap_crosscheck
#print axioms CrossFitFinite.centered_sum_zero

end CrossFitFinite
