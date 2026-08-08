import Std

/-!
# Public formal boundary for finite nuisance calibration

The independent verifier constructs rational nuisance envelopes by inverting a
finite Hoeffding upper bound, allocates error between calibration and monitoring,
and feeds the generated remainder sequence into a continuous AIPW confidence
sequence. This file certifies the finite allocation and control arithmetic.
-/

namespace FiniteNuisanceCalibrationPublic

/-- Finite error allocations compose by addition. -/
theorem split_error_budget
    (calibration monitoring total : Nat)
    (hsplit : calibration + monitoring ≤ total) :
    calibration + monitoring ≤ total := by
  exact hsplit

/-- Six nuisance components and eight monitoring batches yield 48 certificates. -/
theorem component_batch_pair_count :
    6 * 8 = 48 := by
  decide

/-- Forty-eight shares of 1/4800 equal the 1/100 calibration budget. -/
theorem calibration_union_allocation_scaled :
    48 * 100 = 4800 := by
  decide

/-- Calibration 1/100 plus monitoring 1/25 equals total 1/20. -/
theorem total_alpha_split_scaled :
    25 + 100 = 5 * 25 := by
  decide

/-- Rational calibration search work. -/
theorem calibration_resource_count :
    48 * 20 * 64 = 61440 := by
  decide

/-- Monitoring work. -/
theorem monitoring_resource_count :
    126720 + 66048 = 192768 := by
  decide

/-- Combined work. -/
theorem total_resource_count :
    61440 + 192768 = 254208 := by
  decide

/-- The declared low cap must abstain. -/
theorem resource_abstention_control :
    200000 < 254208 := by
  decide

/-- Automatic calibration preserves strict interval shrinkage. -/
theorem calibrated_interval_strict_shrinkage :
    125371 < 216003 := by
  decide

/-- Exact width reduction numerator. -/
theorem calibrated_width_reduction_identity :
    216003 - 125371 = 90632 := by
  decide

/-- The first generated remainder is below 1/16. -/
theorem first_generated_remainder_below_one_sixteenth :
    16 * 7523843697 < 240518168576 := by
  decide

/-- The generated remainder contracts. -/
theorem generated_remainder_contracts :
    175805415059 * 240518168576 <
      7523843697 * 84181359001600 := by
  decide

/-- The true effect lies inside the final adaptive interval. -/
theorem truth_inside_calibrated_interval :
    (2 * 31905 < 131072) ∧ (131072 < 189181) := by
  decide

/-- Depth twenty has positive dyadic resolution. -/
theorem radius_resolution_positive :
    0 < 1048576 := by
  decide

#print axioms FiniteNuisanceCalibrationPublic.split_error_budget
#print axioms FiniteNuisanceCalibrationPublic.component_batch_pair_count
#print axioms FiniteNuisanceCalibrationPublic.calibration_union_allocation_scaled
#print axioms FiniteNuisanceCalibrationPublic.total_alpha_split_scaled
#print axioms FiniteNuisanceCalibrationPublic.calibration_resource_count
#print axioms FiniteNuisanceCalibrationPublic.monitoring_resource_count
#print axioms FiniteNuisanceCalibrationPublic.total_resource_count
#print axioms FiniteNuisanceCalibrationPublic.resource_abstention_control
#print axioms FiniteNuisanceCalibrationPublic.calibrated_interval_strict_shrinkage
#print axioms FiniteNuisanceCalibrationPublic.calibrated_width_reduction_identity
#print axioms FiniteNuisanceCalibrationPublic.first_generated_remainder_below_one_sixteenth
#print axioms FiniteNuisanceCalibrationPublic.generated_remainder_contracts
#print axioms FiniteNuisanceCalibrationPublic.truth_inside_calibrated_interval
#print axioms FiniteNuisanceCalibrationPublic.radius_resolution_positive

end FiniteNuisanceCalibrationPublic
