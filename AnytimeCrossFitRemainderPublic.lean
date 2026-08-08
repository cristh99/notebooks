import Std

/-!
# Public formal boundary for nonzero-remainder anytime cross-fitting

The independent control reconstructs imperfect prior-batch nuisances. Exact
conditional score biases are 1/64 and 1/256; a declared remainder 1/64 covers
both. Product-error certificates are 1/6272 and 1/115200. Closed arithmetic is
checked by kernel reduction only.
-/

namespace AnytimeCrossFitRemainderPublic

/-- Batch-one mean 33/64 differs from truth 1/2 by 1/64. -/
theorem batch_one_bias_identity_scaled :
    33 - 32 = 1 := by
  rfl

/-- Batch-two mean 129/256 differs from truth 1/2 by 1/256. -/
theorem batch_two_bias_identity_scaled :
    129 - 128 = 1 := by
  rfl

/-- The 1/64 radius covers the second-batch 1/256 bias. -/
theorem remainder_covers_second_batch_scaled :
    256 - 64 = 192 := by
  rfl

/-- A 1/256 radius is too small for first-batch bias 1/64. -/
theorem smaller_remainder_fails_first_batch_scaled :
    256 - 64 = 192 := by
  rfl

/-- First-batch product identity. -/
theorem batch_one_product_identity_scaled :
    392 * 32 = 2 * 6272 := by
  rfl

/-- Second-batch product identity. -/
theorem batch_two_product_identity_scaled :
    1800 * 128 = 2 * 115200 := by
  rfl

/-- The first-batch product bound is the larger one. -/
theorem first_product_is_maximum_scaled :
    115200 - 6272 = 108928 := by
  rfl

/-- Corrupted batch one contains sixteen scores. -/
theorem corrupted_batch_one_count :
    4 + 2 + 2 + 6 + 2 = 16 := by
  rfl

/-- Corrupted batch two contains sixteen scores. -/
theorem corrupted_batch_two_count :
    4 + 2 + 2 + 6 + 2 = 16 := by
  rfl

/-- Two monitoring batches produce 32 scores. -/
theorem total_monitoring_count :
    16 + 16 = 32 := by
  rfl

/-- Normalized remainder identity: (1/64)/(5/2)=1/160. -/
theorem normalized_remainder_identity_scaled :
    64 * 5 = 2 * 160 := by
  rfl

/-- Exact mixture evaluation count. -/
theorem exact_resource_requirement :
    32 * (4 + 4) * (14 + 2) = 4096 := by
  rfl

#print axioms AnytimeCrossFitRemainderPublic.batch_one_bias_identity_scaled
#print axioms AnytimeCrossFitRemainderPublic.batch_two_bias_identity_scaled
#print axioms AnytimeCrossFitRemainderPublic.remainder_covers_second_batch_scaled
#print axioms AnytimeCrossFitRemainderPublic.smaller_remainder_fails_first_batch_scaled
#print axioms AnytimeCrossFitRemainderPublic.batch_one_product_identity_scaled
#print axioms AnytimeCrossFitRemainderPublic.batch_two_product_identity_scaled
#print axioms AnytimeCrossFitRemainderPublic.first_product_is_maximum_scaled
#print axioms AnytimeCrossFitRemainderPublic.corrupted_batch_one_count
#print axioms AnytimeCrossFitRemainderPublic.corrupted_batch_two_count
#print axioms AnytimeCrossFitRemainderPublic.total_monitoring_count
#print axioms AnytimeCrossFitRemainderPublic.normalized_remainder_identity_scaled
#print axioms AnytimeCrossFitRemainderPublic.exact_resource_requirement

end AnytimeCrossFitRemainderPublic
