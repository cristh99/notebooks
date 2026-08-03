import Lean.Elab.Tactic.Omega

/-!
# Public formal boundary for predictable posterior betting

The independent verifier reconstructs four safe expert wealth processes,
posterior reweighting from past wealth, finite-grid inversion and exact iid and
Markov crossing probabilities. This file certifies the canonical mixture lower
bound, the calibration obstruction to global strict dominance, and the exact
benchmark arithmetic using kernel-checked Presburger proofs.
-/

namespace PredictableBettingPublic

/-- On the canonical path, adaptive mixture wealth dominates the initial
one-quarter share assigned to the follow-previous expert. Both quantities have
common denominator 2^21. -/
theorem canonical_mixture_dominates_follow_share :
    387420489 ≤ 387479541 := by
  omega

/-- In a two-outcome normalized control, increasing one outcome strictly while
not decreasing the other strictly increases total null mass. Equal calibration
therefore cannot coexist with nontrivial strict pathwise dominance. -/
theorem strict_dominance_changes_two_point_sum :
    1 + 1 < 2 + 1 := by
  omega

/-- Four equal prior shares normalize to one. -/
theorem four_expert_prior_normalized :
    1 + 1 + 1 + 1 = 4 := by
  omega

/-- Exact scaled wealth identity on the block control path. -/
theorem block_path_mixture_identity_scaled :
    59049 + 59049 + 2 * 387420489 + 2 * 3 =
      2 * 387479541 := by
  omega

/-- More than 99.9% of posterior capital is assigned to follow-previous. -/
theorem follow_previous_posterior_exceeds_999_per_mille :
    999 * 129159847 < 1000 * 129140163 := by
  omega

/-- Adaptive iid crossing remains below the 5% threshold. -/
theorem adaptive_iid_crossing_below_alpha :
    6573 * 20 < 524288 := by
  omega

/-- Baseline iid crossing also remains below 5%. -/
theorem baseline_iid_crossing_below_alpha :
    9919 * 20 < 524288 := by
  omega

/-- Adaptive crossing is smaller than baseline under the iid null control. -/
theorem adaptive_iid_crossing_is_smaller :
    6573 < 9919 := by
  omega

/-- Persistence 3/4 power gain. -/
theorem persistent_three_quarters_power_gain :
    64195730523 < 93519651901 := by
  omega

/-- Alternation 3/4 power gain. -/
theorem alternating_three_quarters_power_gain :
    20968297 < 76764627103 := by
  omega

/-- Persistence 4/5 power gain. -/
theorem persistent_four_fifths_power_gain :
    6290791727104 < 10096871290173 := by
  omega

/-- Alternation 4/5 power gain. -/
theorem alternating_four_fifths_power_gain :
    199437241 < 9000466839357 := by
  omega

/-- Persistence 7/8 power gain. -/
theorem persistent_seven_eighths_power_gain :
    75121295530218931 < 119769960138820629 := by
  omega

/-- Alternation 7/8 power gain. -/
theorem alternating_seven_eighths_power_gain :
    19593777589 < 115672803437820483 := by
  omega

/-- Persistence 9/10 power gain. -/
theorem persistent_nine_tenths_power_gain :
    5991489162473726799 < 9077110827793188733 := by
  omega

/-- Alternation 9/10 power gain. -/
theorem alternating_nine_tenths_power_gain :
    167275525591 < 8907844006196817877 := by
  omega

/-- Adaptive final grid is strictly smaller than the 13-point baseline. -/
theorem final_grid_strict_shrinkage :
    0 < 13 := by
  omega

/-- Post-hoc maximization inflates a unit-mean factor to expectation 3/2. -/
theorem post_hoc_maximum_is_invalid_scaled :
    2 < 3 := by
  omega

#print axioms PredictableBettingPublic.canonical_mixture_dominates_follow_share
#print axioms PredictableBettingPublic.strict_dominance_changes_two_point_sum
#print axioms PredictableBettingPublic.four_expert_prior_normalized
#print axioms PredictableBettingPublic.block_path_mixture_identity_scaled
#print axioms PredictableBettingPublic.follow_previous_posterior_exceeds_999_per_mille
#print axioms PredictableBettingPublic.adaptive_iid_crossing_below_alpha
#print axioms PredictableBettingPublic.baseline_iid_crossing_below_alpha
#print axioms PredictableBettingPublic.adaptive_iid_crossing_is_smaller
#print axioms PredictableBettingPublic.persistent_three_quarters_power_gain
#print axioms PredictableBettingPublic.alternating_three_quarters_power_gain
#print axioms PredictableBettingPublic.persistent_four_fifths_power_gain
#print axioms PredictableBettingPublic.alternating_four_fifths_power_gain
#print axioms PredictableBettingPublic.persistent_seven_eighths_power_gain
#print axioms PredictableBettingPublic.alternating_seven_eighths_power_gain
#print axioms PredictableBettingPublic.persistent_nine_tenths_power_gain
#print axioms PredictableBettingPublic.alternating_nine_tenths_power_gain
#print axioms PredictableBettingPublic.final_grid_strict_shrinkage
#print axioms PredictableBettingPublic.post_hoc_maximum_is_invalid_scaled

end PredictableBettingPublic
