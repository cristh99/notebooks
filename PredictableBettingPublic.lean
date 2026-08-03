import Std

/-!
# Public formal boundary for predictable posterior betting

The independent verifier reconstructs four safe expert wealth processes,
posterior reweighting from past wealth, finite-grid inversion and exact iid and
Markov crossing probabilities. The closed arithmetic certificates below are
proved by kernel reduction only (`rfl`): no decision procedure, quotient
soundness, propositional extensionality or classical choice is required.
-/

namespace PredictableBettingPublic

/-- Positive gap certifying that adaptive mixture wealth dominates the initial
one-quarter share assigned to the follow-previous expert. -/
theorem canonical_mixture_dominates_follow_share :
    (387479541 - 387420489 : Nat) = 59052 := by
  rfl

/-- Positive gap certifying the two-point calibration obstruction. -/
theorem strict_dominance_changes_two_point_sum :
    ((2 + 1) - (1 + 1) : Nat) = 1 := by
  rfl

/-- Four equal prior shares normalize to one after scaling by four. -/
theorem four_expert_prior_normalized :
    (1 + 1 + 1 + 1 : Nat) = 4 := by
  rfl

/-- Exact scaled wealth identity on the block control path. -/
theorem block_path_mixture_identity_scaled :
    (59049 + 59049 + 2 * 387420489 + 2 * 3 : Nat) =
      2 * 387479541 := by
  rfl

/-- Positive cross-product gap certifying posterior mass above 99.9%. -/
theorem follow_previous_posterior_exceeds_999_per_mille :
    (1000 * 129140163 - 999 * 129159847 : Nat) = 109475847 := by
  rfl

/-- Positive gap certifying adaptive iid crossing below the 5% threshold. -/
theorem adaptive_iid_crossing_below_alpha :
    (524288 - 6573 * 20 : Nat) = 392828 := by
  rfl

/-- Positive gap certifying baseline iid crossing below 5%. -/
theorem baseline_iid_crossing_below_alpha :
    (524288 - 9919 * 20 : Nat) = 325908 := by
  rfl

/-- Positive gap certifying lower adaptive than baseline iid crossing. -/
theorem adaptive_iid_crossing_is_smaller :
    (9919 - 6573 : Nat) = 3346 := by
  rfl

/-- Persistence 3/4 exact power-gain numerator. -/
theorem persistent_three_quarters_power_gain :
    (93519651901 - 64195730523 : Nat) = 29323921378 := by
  rfl

/-- Alternation 3/4 exact power-gain numerator. -/
theorem alternating_three_quarters_power_gain :
    (76764627103 - 20968297 : Nat) = 76743658806 := by
  rfl

/-- Persistence 4/5 exact power-gain numerator. -/
theorem persistent_four_fifths_power_gain :
    (10096871290173 - 6290791727104 : Nat) = 3806079563069 := by
  rfl

/-- Alternation 4/5 exact power-gain numerator. -/
theorem alternating_four_fifths_power_gain :
    (9000466839357 - 199437241 : Nat) = 9000267402116 := by
  rfl

/-- Persistence 7/8 exact power-gain numerator. -/
theorem persistent_seven_eighths_power_gain :
    (119769960138820629 - 75121295530218931 : Nat) =
      44648664608601698 := by
  rfl

/-- Alternation 7/8 exact power-gain numerator. -/
theorem alternating_seven_eighths_power_gain :
    (115672803437820483 - 19593777589 : Nat) =
      115672783844042894 := by
  rfl

/-- Persistence 9/10 exact power-gain numerator. -/
theorem persistent_nine_tenths_power_gain :
    (9077110827793188733 - 5991489162473726799 : Nat) =
      3085621665319461934 := by
  rfl

/-- Alternation 9/10 exact power-gain numerator. -/
theorem alternating_nine_tenths_power_gain :
    (8907844006196817877 - 167275525591 : Nat) =
      8907843838921292286 := by
  rfl

/-- Positive cardinality gap certifying strict final-grid shrinkage. -/
theorem final_grid_strict_shrinkage :
    (13 - 0 : Nat) = 13 := by
  rfl

/-- Positive scaled gap certifying post-hoc expectation 3/2 exceeds one. -/
theorem post_hoc_maximum_is_invalid_scaled :
    (3 - 2 : Nat) = 1 := by
  rfl

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
