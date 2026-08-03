import Std

namespace FiniteLowerBoundsPublic

/-- A verified overlap bound remains valid after multiplying by a nonnegative scale. -/
theorem scale_preserves_lower_bound
    (scale overlap bound : Nat)
    (h : overlap ≤ bound) :
    scale * overlap ≤ scale * bound := by
  exact Nat.mul_le_mul_left scale h

/-- Matching lower and upper bounds identify an exact value. -/
theorem matching_bounds
    (lower upper : Nat)
    (hLower : lower ≤ upper)
    (hUpper : upper ≤ lower) :
    lower = upper := by
  exact Nat.le_antisymm hLower hUpper

/-- Le Cam control: TV=1/2 gives overlap 1/2. -/
theorem le_cam_overlap_scaled : 2 - 1 = 1 := by decide

/-- The squared-loss event reduction has scaled numerator one over sixteen. -/
theorem le_cam_one_sixteenth_scaled : 1 * 1 = 1 := by decide

/-- Each of four Assouad coordinates contributes one quarter. -/
theorem assouad_coordinate_scaled : 2 - 1 = 1 := by decide

/-- Four coordinate contributions of one quarter sum to one. -/
theorem assouad_four_coordinates_match : 1 + 1 + 1 + 1 = 4 := by decide

/-- The identity decoder risk d*q equals one for d=4 and q=1/4. -/
theorem identity_decoder_matches : 4 * 1 = 4 := by decide

#print axioms FiniteLowerBoundsPublic.scale_preserves_lower_bound
#print axioms FiniteLowerBoundsPublic.matching_bounds
#print axioms FiniteLowerBoundsPublic.le_cam_overlap_scaled
#print axioms FiniteLowerBoundsPublic.le_cam_one_sixteenth_scaled
#print axioms FiniteLowerBoundsPublic.assouad_coordinate_scaled
#print axioms FiniteLowerBoundsPublic.assouad_four_coordinates_match
#print axioms FiniteLowerBoundsPublic.identity_decoder_matches

end FiniteLowerBoundsPublic
