import Mathlib

/-!
# Finite algebraic boundary for proof-carrying Fano certificates

The measure-theoretic Fano inequality remains established external mathematics.
This file formalizes the algebraic decoding reduction and the exact rational
control values used by the finite compiler.
-/

namespace FanoFinite

/-- A certified lower bound on decoding error transports to squared risk. -/
theorem error_lower_bound_to_squared_risk
    (radiusSq errorLower errorProbability risk : ℝ)
    (hRadius : 0 ≤ radiusSq)
    (hError : errorLower ≤ errorProbability)
    (hRisk : radiusSq * errorProbability ≤ risk) :
    radiusSq * errorLower ≤ risk := by
  have hScaled := mul_le_mul_of_nonneg_left hError hRadius
  linarith

/-- Distinct one-hot targets have squared Euclidean separation two. -/
theorem one_hot_pair_squared_distance :
    ((1 : ℝ) - 0)^2 + (0 - 1)^2 = 2 := by
  norm_num

/-- Each row of the eight-world symmetric channel is a probability law. -/
theorem symmetric_eight_channel_row_sum :
    (1 / 4 : ℝ) + 7 * (3 / 28 : ℝ) = 1 := by
  norm_num

/-- The uniform-prior MAP decoder has exact classification risk three quarters. -/
theorem symmetric_eight_map_classification_risk :
    7 * (3 / 28 : ℝ) = 3 / 4 := by
  norm_num

/-- With one-hot targets, each classification error contributes squared loss two. -/
theorem symmetric_eight_map_squared_risk :
    2 * (7 * (3 / 28 : ℝ)) = 3 / 2 := by
  norm_num

/-- The certified decimal floor produced by the rational log enclosure is positive. -/
theorem certified_fano_error_floor_positive :
    (0 : ℝ) < 638931438667 / 1000000000000 := by
  norm_num

/-- The certified squared-loss floor is below the explicit MAP upper witness. -/
theorem certified_squared_floor_below_map :
    (319465719333 / 1000000000000 : ℝ) < 3 / 2 := by
  norm_num

#print axioms FanoFinite.error_lower_bound_to_squared_risk
#print axioms FanoFinite.one_hot_pair_squared_distance
#print axioms FanoFinite.symmetric_eight_channel_row_sum
#print axioms FanoFinite.symmetric_eight_map_classification_risk
#print axioms FanoFinite.symmetric_eight_map_squared_risk
#print axioms FanoFinite.certified_fano_error_floor_positive
#print axioms FanoFinite.certified_squared_floor_below_map

end FanoFinite
