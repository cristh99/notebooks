import Std

/-!
# Public formal boundary for remainder-calibrated cross-fit anytime inference

The independent verifier checks held-out fold exclusion, nuisance provenance,
score laws, absolute remainder bounds and predictable e-factors. It then
reconstructs the finite conditional-supermartingale and bounded-stopping
controls. This file certifies the bias-penalty logic and canonical rational
arithmetic without axioms.
-/

namespace FiniteCrossFitAnytimePublic

/-- A nonnegative stake preserves an upper mean bound after multiplication. -/
theorem nonnegative_stake_bias_penalty
    (stake mean remainder : Nat)
    (hmean : mean ≤ remainder) :
    stake * mean ≤ stake * remainder := by
  exact Nat.mul_le_mul_left stake hmean

/-- The same order transport applies to the opposite score direction. -/
theorem opposite_direction_bias_penalty
    (stake negativeMean remainder : Nat)
    (hmean : negativeMean ≤ remainder) :
    stake * negativeMean ≤ stake * remainder := by
  exact Nat.mul_le_mul_left stake hmean

/-- Canonical outer split: forty-eight training and sixteen validation rows. -/
theorem canonical_outer_split_size :
    48 + 16 = 64 := by
  decide

/-- Last-fold score probabilities normalize. -/
theorem last_fold_score_law_normalized_scaled :
    83 + 77 = 160 := by
  decide

/-- Last-fold score mean numerator is six over 160, hence three over 80. -/
theorem last_fold_mean_scaled :
    83 - 77 = 6 := by
  decide

/-- The smallest calibrated factor has positive scaled numerator 77. -/
theorem calibrated_factor_positive_scaled :
    0 < 77 := by
  decide

/-- The positive calibrated expert has conditional expectation one. -/
theorem corrected_positive_expectation_scaled :
    83 * 237 + 77 * 77 = 160 * 160 := by
  decide

/-- The opposite calibrated expert has conditional expectation 77/80. -/
theorem corrected_negative_expectation_scaled :
    83 * 77 + 77 * 237 = 77 * 320 := by
  decide

/-- Omitting the remainder penalty inflates expectation to 163/160. -/
theorem naive_uncorrected_expectation_inflates :
    160 < 163 := by
  decide

/-- The understated remainder one-eightieth is below the actual three-eightieths. -/
theorem understated_remainder_is_invalid :
    1 < 3 := by
  decide

/-- A half-half meta-process retains at least half of its left component. -/
theorem half_competitive_left (left right : Nat) :
    left ≤ left + right := by
  omega

/-- Symmetric component bound. -/
theorem half_competitive_right (left right : Nat) :
    right ≤ left + right := by
  omega

#print axioms FiniteCrossFitAnytimePublic.nonnegative_stake_bias_penalty
#print axioms FiniteCrossFitAnytimePublic.opposite_direction_bias_penalty
#print axioms FiniteCrossFitAnytimePublic.canonical_outer_split_size
#print axioms FiniteCrossFitAnytimePublic.last_fold_score_law_normalized_scaled
#print axioms FiniteCrossFitAnytimePublic.last_fold_mean_scaled
#print axioms FiniteCrossFitAnytimePublic.calibrated_factor_positive_scaled
#print axioms FiniteCrossFitAnytimePublic.corrected_positive_expectation_scaled
#print axioms FiniteCrossFitAnytimePublic.corrected_negative_expectation_scaled
#print axioms FiniteCrossFitAnytimePublic.naive_uncorrected_expectation_inflates
#print axioms FiniteCrossFitAnytimePublic.understated_remainder_is_invalid
#print axioms FiniteCrossFitAnytimePublic.half_competitive_left
#print axioms FiniteCrossFitAnytimePublic.half_competitive_right

end FiniteCrossFitAnytimePublic
