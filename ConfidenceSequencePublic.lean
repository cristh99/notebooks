import Std

/-!
# Public formal boundary for finite-grid anytime confidence sequences

The independent verifier checks bounded observations, globally safe fixed betting
fractions, nonnegative factors, normalized mixtures and exact grid inversion.
Ville's inequality is an established theorem; this file certifies the logical
inversion step and closed arithmetic by kernel reduction only.
-/

namespace ConfidenceSequencePublic

/-- If exclusion implies threshold crossing, a crossing bound transfers to the
exclusion event through monotonicity. -/
theorem inversion_transfers_crossing_bound
    {Outcome : Type}
    (excluded crossed : Outcome → Prop)
    (eventMass : (Outcome → Prop) → Nat)
    (alpha : Nat)
    (hMonotone :
      ∀ left right,
        (∀ outcome, left outcome → right outcome) →
        eventMass left ≤ eventMass right)
    (hSubset : ∀ outcome, excluded outcome → crossed outcome)
    (hCrossing : eventMass crossed ≤ alpha) :
    eventMass excluded ≤ alpha := by
  exact Nat.le_trans (hMonotone excluded crossed hSubset) hCrossing

/-- Eight equal rational mixture weights sum to one after scaling by eight. -/
theorem mixture_weights_normalized :
    decide (8 * 1 = 8) = true := by
  rfl

/-- The grid from zero to one by twentieths has twenty-one points. -/
theorem declared_grid_size :
    decide (20 + 1 = 21) = true := by
  rfl

/-- Alpha one twentieth corresponds to threshold twenty. -/
theorem threshold_is_twenty :
    decide (20 * 1 = 20) = true := by
  rfl

/-- The affine factors at the global lambda endpoints have nonnegative corners. -/
theorem endpoint_factor_corners_nonnegative :
    decide
      (0 ≤ 1 ∧ 0 ≤ 0 ∧ 0 ≤ 2 ∧ 0 ≤ 1 ∧
       0 ≤ 1 ∧ 0 ≤ 2 ∧ 0 ≤ 0 ∧ 0 ≤ 1) = true := by
  rfl

/-- Final grid indices twelve through seventeen contain six points. -/
theorem final_grid_interval_size :
    decide (17 - 12 + 1 = 6) = true := by
  rfl

/-- Grid index fifteen equals the reference mean three quarters. -/
theorem reference_mean_grid_identity :
    decide (15 * 4 = 3 * 20) = true := by
  rfl

/-- The largest reference e-value 527/512 remains below twenty. -/
theorem reference_never_crosses_control_threshold :
    decide (527 < 20 * 512) = true := by
  rfl

/-- Post-hoc maximization inflates a valid mean-one pair to five quarters. -/
theorem post_hoc_maximum_inflates_mean :
    decide (4 < 5) = true := by
  rfl

#print axioms ConfidenceSequencePublic.inversion_transfers_crossing_bound
#print axioms ConfidenceSequencePublic.mixture_weights_normalized
#print axioms ConfidenceSequencePublic.declared_grid_size
#print axioms ConfidenceSequencePublic.threshold_is_twenty
#print axioms ConfidenceSequencePublic.endpoint_factor_corners_nonnegative
#print axioms ConfidenceSequencePublic.final_grid_interval_size
#print axioms ConfidenceSequencePublic.reference_mean_grid_identity
#print axioms ConfidenceSequencePublic.reference_never_crosses_control_threshold
#print axioms ConfidenceSequencePublic.post_hoc_maximum_inflates_mean

end ConfidenceSequencePublic
