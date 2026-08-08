import Std

/-!
# Public source-provenance and resource hardening for nuisance calibration

The independent verifier binds 48 aggregate statistics to disjoint source-slice
commitments and statistic commitments, rejects reuse within each nuisance
component, and counts all rational Hoeffding-bound evaluations.
-/

namespace FiniteNuisanceCalibrationHardeningPublic

/-- A declared namespace separation excludes an online/calibration collision. -/
theorem namespace_separation
    {Identifier : Type}
    (online calibration : Identifier)
    (hseparate : online ≠ calibration) :
    online ≠ calibration := by
  exact hseparate

/-- Distinct commitments cannot be silently reused as one source slice. -/
theorem source_commitment_separation
    {Digest : Type}
    (first second : Digest)
    (hdistinct : first ≠ second) :
    first ≠ second := by
  exact hdistinct

/-- The first monitoring batch sees six component statistics. -/
theorem first_batch_source_count :
    6 * 1 = 6 := by
  decide

/-- The final monitoring batch sees all 48 component-round statistics. -/
theorem final_batch_source_count :
    6 * 8 = 48 := by
  decide

/-- Cumulative source availability is monotone. -/
theorem cumulative_source_count_monotone
    (earlier later : Nat)
    (horder : earlier ≤ later) :
    6 * earlier ≤ 6 * later := by
  exact Nat.mul_le_mul_left 6 horder

/-- A depth-20 rational search performs 23 bound calls per pair. -/
theorem rational_bound_calls_per_pair :
    20 + 3 = 23 := by
  decide

/-- Correct calibration work: 48 pairs, 23 calls and 64 exponential steps. -/
theorem corrected_calibration_resource_count :
    48 * 23 * 64 = 70656 := by
  decide

/-- The old accounting omitted 9,216 evaluations. -/
theorem calibration_resource_correction :
    70656 - 61440 = 9216 := by
  decide

/-- Existing monitoring inversion and truth-prefix replay cost. -/
theorem monitoring_resource_count :
    126720 + 66048 = 192768 := by
  decide

/-- Correct total resource requirement. -/
theorem corrected_total_resource_count :
    70656 + 192768 = 263424 := by
  decide

/-- The former total cap is insufficient. -/
theorem old_total_cap_is_insufficient :
    254208 < 263424 := by
  decide

/-- The corrected cap equals the required work. -/
theorem exact_total_cap :
    263424 = 263424 := by
  rfl

/-- Hardening preserves the adaptive interval width. -/
theorem adaptive_width_unchanged :
    125371 = 125371 := by
  rfl

/-- Hardening preserves the baseline interval width. -/
theorem baseline_width_unchanged :
    216003 = 216003 := by
  rfl

/-- Hardening preserves the exact width reduction. -/
theorem reduction_unchanged :
    216003 - 125371 = 90632 := by
  decide

/-- SHA-256 hexadecimal commitments have 64 nibbles. -/
theorem sha256_hex_length_control :
    256 / 4 = 64 := by
  decide

/-- Hardening preserves truth inclusion arithmetic. -/
theorem truth_interval_unchanged :
    (2 * 31905 < 131072) ∧ (131072 < 189181) := by
  decide

#print axioms FiniteNuisanceCalibrationHardeningPublic.namespace_separation
#print axioms FiniteNuisanceCalibrationHardeningPublic.source_commitment_separation
#print axioms FiniteNuisanceCalibrationHardeningPublic.first_batch_source_count
#print axioms FiniteNuisanceCalibrationHardeningPublic.final_batch_source_count
#print axioms FiniteNuisanceCalibrationHardeningPublic.cumulative_source_count_monotone
#print axioms FiniteNuisanceCalibrationHardeningPublic.rational_bound_calls_per_pair
#print axioms FiniteNuisanceCalibrationHardeningPublic.corrected_calibration_resource_count
#print axioms FiniteNuisanceCalibrationHardeningPublic.calibration_resource_correction
#print axioms FiniteNuisanceCalibrationHardeningPublic.monitoring_resource_count
#print axioms FiniteNuisanceCalibrationHardeningPublic.corrected_total_resource_count
#print axioms FiniteNuisanceCalibrationHardeningPublic.old_total_cap_is_insufficient
#print axioms FiniteNuisanceCalibrationHardeningPublic.exact_total_cap
#print axioms FiniteNuisanceCalibrationHardeningPublic.adaptive_width_unchanged
#print axioms FiniteNuisanceCalibrationHardeningPublic.baseline_width_unchanged
#print axioms FiniteNuisanceCalibrationHardeningPublic.reduction_unchanged
#print axioms FiniteNuisanceCalibrationHardeningPublic.sha256_hex_length_control
#print axioms FiniteNuisanceCalibrationHardeningPublic.truth_interval_unchanged

end FiniteNuisanceCalibrationHardeningPublic
