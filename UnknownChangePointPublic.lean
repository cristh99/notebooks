import Std

/-!
# Public formal boundary for the finite unknown-change detector

The executable audit supplies a finite signed-manifest control, exact resource
counts, predictable learner selection and rational interval endpoints. These
theorems certify the logical obstruction and the arithmetic identities used by
the public evidence capsule; they do not formalize the full probabilistic
change-point theorem.
-/

namespace UnknownChangePointPublic

/-- Exact recovery of a finite change label from an evidence signature. -/
def ExactDecoder {World Signature Label : Type}
    (signature : World → Signature)
    (label : World → Label) : Prop :=
  ∃ decoder : Signature → Label,
    ∀ world, decoder (signature world) = label world

/-- Two worlds with equal admissible evidence and different change labels rule
out exact recovery from that evidence grammar. -/
theorem indistinguishable_changes_block_exact_decoder
    {World Signature Label : Type}
    (signature : World → Signature)
    (label : World → Label)
    {left right : World}
    (hsame : signature left = signature right)
    (hdifferent : label left ≠ label right) :
    ¬ ExactDecoder signature label := by
  intro hexact
  rcases hexact with ⟨decoder, hdecoder⟩
  apply hdifferent
  calc
    label left = decoder (signature left) := (hdecoder left).symm
    _ = decoder (signature right) := by rw [hsame]
    _ = label right := hdecoder right

/-- Factorization through the evidence signature supplies an exact decoder. -/
theorem factorized_change_is_identified
    {World Signature Label : Type}
    (signature : World → Signature)
    (label : World → Label)
    (decoder : Signature → Label)
    (hfactor : ∀ world, decoder (signature world) = label world) :
    ExactDecoder signature label := by
  exact ⟨decoder, hfactor⟩

/-- Honest resource accounting: detector, adaptive monitor, four-bet baseline,
and one signature verification sum to 373888. -/
theorem corrected_total_evaluations :
    38016 + 104959 + 230912 + 1 = 373888 := by
  decide

/-- The former reported resource total is strictly too small. -/
theorem former_resource_total_is_insufficient :
    289408 < 373888 := by
  decide

/-- Adaptive interval width identity after putting both endpoints over 262144. -/
theorem adaptive_width_identity :
    164015 - 2 * 50571 = 62873 := by
  decide

/-- Baseline interval width identity after putting 6579/16384 over 262144. -/
theorem baseline_width_identity :
    175259 - 16 * 6579 = 69995 := by
  decide

/-- The adaptive interval is strictly narrower, with exact gain 7122/262144. -/
theorem adaptive_width_gain :
    (62873 < 69995) ∧ (69995 - 62873 = 7122) := by
  decide

/-- The detector's allocated alpha 1/12800 fits inside change alpha 1/100. -/
theorem detector_alpha_fits_change_budget :
    100 < 12800 := by
  decide

/-- Eleven monitoring batches split into six global and five R1 selections. -/
theorem selection_horizon_partition :
    6 + 5 = 11 := by
  decide

#print axioms UnknownChangePointPublic.indistinguishable_changes_block_exact_decoder
#print axioms UnknownChangePointPublic.factorized_change_is_identified
#print axioms UnknownChangePointPublic.corrected_total_evaluations
#print axioms UnknownChangePointPublic.former_resource_total_is_insufficient
#print axioms UnknownChangePointPublic.adaptive_width_identity
#print axioms UnknownChangePointPublic.baseline_width_identity
#print axioms UnknownChangePointPublic.adaptive_width_gain
#print axioms UnknownChangePointPublic.detector_alpha_fits_change_budget
#print axioms UnknownChangePointPublic.selection_horizon_partition

end UnknownChangePointPublic
