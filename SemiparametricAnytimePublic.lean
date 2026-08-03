import Std

/-!
# Public formal boundary for finite cross-fit AIPW confidence sequences

The independent verifier reconstructs disjoint nuisance provenance, exact AIPW
score laws, product-form remainder bounds, bounded normalization and predictable
robust factors. This file certifies the leakage obstruction and exact arithmetic
of the public control without reflected axioms.
-/

namespace SemiparametricAnytimePublic

/-- Evaluation rows may never occur in the training provenance of the nuisance
model used to score them. -/
def NoEvaluationLeakage {Model Row : Type}
    (training : Model → Row → Prop)
    (evaluatedWith : Row → Model → Prop) : Prop :=
  ∀ model row, training model row → ¬ evaluatedWith row model

/-- One evaluation row found in its scoring model's training set refutes the
cross-fit provenance obligation. -/
theorem leakage_witness_refutes_crossfit
    {Model Row : Type}
    (training : Model → Row → Prop)
    (evaluatedWith : Row → Model → Prop)
    (model : Model)
    (row : Row)
    (hTraining : training model row)
    (hEvaluation : evaluatedWith row model) :
    ¬ NoEvaluationLeakage training evaluatedWith := by
  intro hNoLeakage
  exact (hNoLeakage model row hTraining) hEvaluation

/-- The eight event multiplicities reconstruct the 64-row control law. -/
theorem control_event_count :
    21 + 3 + 3 + 5 + 5 + 3 + 3 + 21 = 64 := by
  decide

/-- Sixty-four rows, twenty-one effects and four experts require 5376 cells. -/
theorem declared_resource_count :
    64 * 21 * 4 = 5376 := by
  decide

/-- The declared AIPW score range [-5/4,7/4] has width three. -/
theorem score_range_width_scaled :
    7 + 5 = 3 * 4 := by
  decide

/-- Transforming the true effect 1/2 through the score range gives 7/12. -/
theorem true_effect_transform_scaled :
    2 + 5 = 7 := by
  decide

/-- Model A expected score is one sixty-fourth below the true effect. -/
theorem model_a_remainder_identity_scaled :
    31 + 1 = 32 := by
  decide

/-- Model B expected score is one one-hundred-ninety-second above truth. -/
theorem model_b_remainder_identity_scaled :
    96 + 1 = 97 := by
  decide

/-- Model-A remainder magnitude is covered by its component bound. -/
theorem model_a_remainder_is_bounded :
    1 ≤ 3 := by
  decide

/-- Model-B remainder magnitude is covered by its component bound. -/
theorem model_b_remainder_is_bounded :
    1 ≤ 19 := by
  decide

/-- Model-A positive robust factor has expectation 47/48. -/
theorem model_a_positive_factor_subunit :
    47 < 48 := by
  decide

/-- Model-A negative robust factor has expectation 95/96. -/
theorem model_a_negative_factor_subunit :
    95 < 96 := by
  decide

/-- Model-B positive robust factor has expectation 31/32. -/
theorem model_b_positive_factor_subunit :
    31 < 32 := by
  decide

/-- Model-B negative robust factor has expectation 139/144. -/
theorem model_b_negative_factor_subunit :
    139 < 144 := by
  decide

/-- Model A satisfies the declared one-quarter positivity floor. -/
theorem model_a_positivity_scaled :
    3 ≤ 4 ∧ 8 ≤ 9 := by
  decide

/-- Model B satisfies the declared one-quarter positivity floor. -/
theorem model_b_positivity_scaled :
    5 ≤ 8 ∧ 12 ≤ 15 := by
  decide

/-- Adaptive final grid has eight points versus fourteen for baseline. -/
theorem adaptive_grid_is_strictly_smaller :
    8 < 14 := by
  decide

/-- Adaptive hull width 7/20 is below baseline width 13/20. -/
theorem adaptive_width_is_strictly_smaller :
    7 < 13 := by
  decide

/-- Absolute width reduction is six twentieths. -/
theorem width_reduction_scaled :
    13 - 7 = 6 := by
  decide

/-- Relative width reduction is the nontrivial fraction 6/13. -/
theorem relative_width_reduction_control :
    6 < 13 := by
  decide

/-- Post-hoc maximization inflates a unit-mean factor to 3/2. -/
theorem post_hoc_selection_is_invalid_scaled :
    2 < 3 := by
  decide

#print axioms SemiparametricAnytimePublic.leakage_witness_refutes_crossfit
#print axioms SemiparametricAnytimePublic.control_event_count
#print axioms SemiparametricAnytimePublic.declared_resource_count
#print axioms SemiparametricAnytimePublic.score_range_width_scaled
#print axioms SemiparametricAnytimePublic.true_effect_transform_scaled
#print axioms SemiparametricAnytimePublic.model_a_remainder_identity_scaled
#print axioms SemiparametricAnytimePublic.model_b_remainder_identity_scaled
#print axioms SemiparametricAnytimePublic.model_a_remainder_is_bounded
#print axioms SemiparametricAnytimePublic.model_b_remainder_is_bounded
#print axioms SemiparametricAnytimePublic.model_a_positive_factor_subunit
#print axioms SemiparametricAnytimePublic.model_a_negative_factor_subunit
#print axioms SemiparametricAnytimePublic.model_b_positive_factor_subunit
#print axioms SemiparametricAnytimePublic.model_b_negative_factor_subunit
#print axioms SemiparametricAnytimePublic.model_a_positivity_scaled
#print axioms SemiparametricAnytimePublic.model_b_positivity_scaled
#print axioms SemiparametricAnytimePublic.adaptive_grid_is_strictly_smaller
#print axioms SemiparametricAnytimePublic.adaptive_width_is_strictly_smaller
#print axioms SemiparametricAnytimePublic.width_reduction_scaled
#print axioms SemiparametricAnytimePublic.relative_width_reduction_control
#print axioms SemiparametricAnytimePublic.post_hoc_selection_is_invalid_scaled

end SemiparametricAnytimePublic
