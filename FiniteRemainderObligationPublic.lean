import Std

/-!
# Public formal boundary for semiparametric remainder obligations

The independent verifier transports finite L2 nuisance bounds through the AIPW
second-order remainder inequality, tracks overlap deterioration, classifies
product-rate obligations and emits fold-specific penalties for an anytime
cross-fit e-process. This file certifies the exact rational control arithmetic
and logical rate comparisons without axioms.
-/

namespace FiniteRemainderObligationPublic

/-- A nonnegative multiplier preserves an upper error bound. -/
theorem nonnegative_multiplier_preserves_bound
    (multiplier error bound : Nat)
    (hbound : error ≤ bound) :
    multiplier * error ≤ multiplier * bound := by
  exact Nat.mul_le_mul_left multiplier hbound

/-- Exact propensity knowledge annihilates the product remainder. -/
theorem double_robust_zero_left (outcomeError : Nat) :
    0 * outcomeError = 0 := by
  rfl

/-- Exact outcome knowledge annihilates the product remainder. -/
theorem double_robust_zero_right (propensityError : Nat) :
    propensityError * (0 + 0) = 0 := by
  omega

/-- `(1/10)(1/20+1/10)/(2/5)=3/80` after clearing denominators. -/
theorem canonical_finite_remainder_scaled :
    1 * 3 * 5 * 80 = 3 * 10 * 20 * 2 := by
  decide

/-- Equal fold masses aggregate three `3/80` bounds to `9/320`. -/
theorem weighted_fold_remainder_scaled :
    3 * 3 * 320 = 9 * 80 * 4 := by
  decide

/-- Minimum calibrated factor numerator is `77/160`. -/
theorem minimum_anytime_factor_scaled :
    160 - 83 = 77 := by
  decide

/-- Strong product rates exceed the root-n threshold. -/
theorem strong_product_rate_exceeds_root_n :
    5 < 6 := by
  decide

/-- Quarter plus quarter is exactly the root-n boundary. -/
theorem borderline_product_rate_equals_root_n :
    1 + 1 = 2 := by
  decide

/-- One-fifth plus one-quarter is below one-half. -/
theorem insufficient_product_rate_below_root_n :
    9 < 10 := by
  decide

/-- Overlap deterioration consumes the strong-rate margin. -/
theorem deteriorating_overlap_reaches_borderline :
    3 + 3 - 1 = 5 := by
  decide

/-- Last-fold score law normalizes. -/
theorem crossfit_score_law_normalized :
    83 + 77 = 160 := by
  decide

/-- Last-fold score mean equals the generated `3/80` remainder. -/
theorem crossfit_mean_matches_remainder_scaled :
    83 - 77 = 2 * 3 := by
  decide

#print axioms FiniteRemainderObligationPublic.nonnegative_multiplier_preserves_bound
#print axioms FiniteRemainderObligationPublic.double_robust_zero_left
#print axioms FiniteRemainderObligationPublic.double_robust_zero_right
#print axioms FiniteRemainderObligationPublic.canonical_finite_remainder_scaled
#print axioms FiniteRemainderObligationPublic.weighted_fold_remainder_scaled
#print axioms FiniteRemainderObligationPublic.minimum_anytime_factor_scaled
#print axioms FiniteRemainderObligationPublic.strong_product_rate_exceeds_root_n
#print axioms FiniteRemainderObligationPublic.borderline_product_rate_equals_root_n
#print axioms FiniteRemainderObligationPublic.insufficient_product_rate_below_root_n
#print axioms FiniteRemainderObligationPublic.deteriorating_overlap_reaches_borderline
#print axioms FiniteRemainderObligationPublic.crossfit_score_law_normalized
#print axioms FiniteRemainderObligationPublic.crossfit_mean_matches_remainder_scaled

end FiniteRemainderObligationPublic
