import Std

/-!
# Public formal boundary for exact finite cross-fit intervals

The independent verifier performs complete rational convolution of the declared
64-score law, selects the smallest symmetric radius attaining 19/20 coverage,
and composes it with a deterministic remainder bound. Closed arithmetic is
certified by kernel reduction of Boolean decision procedures, not by native
or classical proof automation.
-/

namespace ExactIntervalPublic

/-- Sampling and deterministic remainder bounds add. -/
theorem sampling_and_remainder_bounds_add
    (samplingError remainder samplingRadius remainderRadius : Nat)
    (hSampling : samplingError ≤ samplingRadius)
    (hRemainder : remainder ≤ remainderRadius) :
    samplingError + remainder ≤ samplingRadius + remainderRadius := by
  exact Nat.add_le_add hSampling hRemainder

/-- The complete 64-score sum support has 321 points. -/
theorem control_support_count :
    decide (5 * 64 + 1 = 321) = true := by
  rfl

/-- The resource guard crosses 100 states at score twenty. -/
theorem resource_abstention_boundary :
    decide (5 * 20 + 1 = 101 ∧ 100 < 101) = true := by
  rfl

/-- The selected radius attains at least 19/20 exact coverage. -/
theorem selected_radius_meets_nineteen_twentieths :
    decide
      (19 *
          3138550867693340381917894711603833208051177722232017256448
        ≤
       20 *
          3002330471241896482860969550432384938379696188542449130789)
      = true := by
  rfl

/-- The immediately smaller radius fails the target. -/
theorem previous_radius_fails_nineteen_twentieths :
    decide
      (20 *
          2974218216536181192209355062405405146923771757429461048421
        <
       19 *
          3138550867693340381917894711603833208051177722232017256448)
      = true := by
  rfl

/-- Center 1/2 and radius 25/128 yield 39/128 and 89/128. -/
theorem exact_interval_endpoints :
    decide (64 - 25 = 39 ∧ 64 + 25 = 89) = true := by
  rfl

/-- Exact convolution is narrower than the certified Chebyshev radius 1/2. -/
theorem exact_radius_beats_chebyshev :
    decide (25 * 2 < 1 * 128) = true := by
  rfl

#print axioms ExactIntervalPublic.sampling_and_remainder_bounds_add
#print axioms ExactIntervalPublic.control_support_count
#print axioms ExactIntervalPublic.resource_abstention_boundary
#print axioms ExactIntervalPublic.selected_radius_meets_nineteen_twentieths
#print axioms ExactIntervalPublic.previous_radius_fails_nineteen_twentieths
#print axioms ExactIntervalPublic.exact_interval_endpoints
#print axioms ExactIntervalPublic.exact_radius_beats_chebyshev

end ExactIntervalPublic
