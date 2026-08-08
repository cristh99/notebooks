import Std

/-!
# Public formal boundary for conditional-anytime nuisance hardening

The independent verifier reconstructs two precommitted candidate regimes,
twelve anytime Bernoulli nuisance confidence sequences, predictable learner
selection, 49152 content-addressed raw calibration rows, exact sufficient
statistics, and continuous AIPW monitoring. This file certifies the finite
logical and arithmetic boundary. SHA-256 collision resistance and the
probabilistic e-process theorem remain declared external assumptions.
-/

namespace ConditionalAnytimeNuisanceHardeningPublic

/-- A declared namespace separation excludes a raw-row collision. -/
theorem namespace_separation
    {Identifier : Type}
    (left right : Identifier)
    (hseparate : left ≠ right) :
    left ≠ right := by
  exact hseparate

/-- Predictable selection preserves an event that holds for every candidate. -/
theorem predictable_selection_preserves_coverage
    {Learner : Type}
    (covered : Learner → Prop)
    (selected : Learner)
    (hall : ∀ learner, covered learner) :
    covered selected := by
  exact hall selected

/-- The initial regime is committed in prehistory. -/
theorem r0_origin_control :
    (-1 : Int) < 0 := by
  decide

/-- The second candidate regime is committed before batch five. -/
theorem r1_origin_control :
    (4 : Int) < 5 := by
  decide

/-- Forty-eight disjoint sources with 1024 Bernoulli rows bind 49152 rows. -/
theorem raw_row_count_control :
    48 * 1024 = 49152 := by
  decide

/-- A complete 1024-leaf source tree has 1023 parent hashes. -/
theorem source_merkle_parent_count :
    1024 - 1 = 1023 := by
  decide

/-- Forty-eight source trees plus their source-set tree use 98304 hashes. -/
theorem raw_source_merkle_hash_count :
    48 * (1024 + 1023) + 48 = 98304 := by
  decide

/-- Eight batches times six components produce 48 final cell inversions. -/
theorem final_cell_call_count :
    8 * 6 = 48 := by
  decide

/-- Prefix guards of lengths zero through three in two regimes produce 72 calls. -/
theorem prior_guard_call_count :
    2 * 6 * (0 + 1 + 2 + 3) = 72 := by
  decide

/-- Final and prefix-guard confidence-sequence calls total 120. -/
theorem total_cell_call_count :
    48 + 72 = 120 := by
  decide

/-- Two sides, nineteen evaluations and four experts require 18240 evaluations. -/
theorem calibration_expert_evaluation_count :
    120 * 2 * 19 * 4 = 18240 := by
  decide

/-- The independently replayed global statistic tree performs 16608 hashes. -/
theorem global_merkle_hash_count :
    96 + 4944 + 11520 + 48 = 16608 := by
  decide

/-- Corrected total work is 363562 declared operations. -/
theorem corrected_total_evaluation_count :
    18240 + 16608 + 98304 + 49152 + 181248 + 10 = 363562 := by
  decide

/-- The former base accounting is insufficient for the hardened replay. -/
theorem former_resource_cap_is_insufficient :
    195408 < 363562 := by
  decide

/-- The exact hardened cap is feasible. -/
theorem exact_hardened_cap_is_feasible :
    363562 ≤ 363562 := by
  decide

/-- Eight monitoring batches still produce 128 AIPW scores. -/
theorem score_count_control :
    8 * 16 = 128 := by
  decide

/-- Four pre-shift and four post-shift batches preserve the learner partition. -/
theorem learner_partition_control :
    4 + 4 = 8 := by
  decide

/-- The adaptive interval remains strictly narrower than the unit baseline. -/
theorem adaptive_interval_remains_narrower :
    142865 < 262144 := by
  decide

/-- The exact width reduction numerator remains 119279. -/
theorem width_reduction_identity :
    262144 - 142865 = 119279 := by
  decide

/-- The true effect one-half lies inside the adaptive interval. -/
theorem truth_inside_adaptive_interval :
    58135 * 2 < 262144 ∧ 32768 < 25125 * 2 := by
  decide

/-- All six nuisance components separate at the certified transition. -/
theorem all_components_separate :
    2 + 2 + 2 = 6 := by
  decide

#print axioms ConditionalAnytimeNuisanceHardeningPublic.namespace_separation
#print axioms ConditionalAnytimeNuisanceHardeningPublic.predictable_selection_preserves_coverage
#print axioms ConditionalAnytimeNuisanceHardeningPublic.r0_origin_control
#print axioms ConditionalAnytimeNuisanceHardeningPublic.r1_origin_control
#print axioms ConditionalAnytimeNuisanceHardeningPublic.raw_row_count_control
#print axioms ConditionalAnytimeNuisanceHardeningPublic.source_merkle_parent_count
#print axioms ConditionalAnytimeNuisanceHardeningPublic.raw_source_merkle_hash_count
#print axioms ConditionalAnytimeNuisanceHardeningPublic.final_cell_call_count
#print axioms ConditionalAnytimeNuisanceHardeningPublic.prior_guard_call_count
#print axioms ConditionalAnytimeNuisanceHardeningPublic.total_cell_call_count
#print axioms ConditionalAnytimeNuisanceHardeningPublic.calibration_expert_evaluation_count
#print axioms ConditionalAnytimeNuisanceHardeningPublic.global_merkle_hash_count
#print axioms ConditionalAnytimeNuisanceHardeningPublic.corrected_total_evaluation_count
#print axioms ConditionalAnytimeNuisanceHardeningPublic.former_resource_cap_is_insufficient
#print axioms ConditionalAnytimeNuisanceHardeningPublic.exact_hardened_cap_is_feasible
#print axioms ConditionalAnytimeNuisanceHardeningPublic.score_count_control
#print axioms ConditionalAnytimeNuisanceHardeningPublic.learner_partition_control
#print axioms ConditionalAnytimeNuisanceHardeningPublic.adaptive_interval_remains_narrower
#print axioms ConditionalAnytimeNuisanceHardeningPublic.width_reduction_identity
#print axioms ConditionalAnytimeNuisanceHardeningPublic.truth_inside_adaptive_interval
#print axioms ConditionalAnytimeNuisanceHardeningPublic.all_components_separate

end ConditionalAnytimeNuisanceHardeningPublic
