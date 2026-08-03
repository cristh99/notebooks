import Mathlib

/-!
# Formal boundary for finite causal identification

The executable public verifier runs the ADMG ID algorithm and evaluates the
identified formulas. This file formalizes the impossibility and arithmetic
cores of the simple, backdoor, front-door and hedge controls.
-/

namespace FiniteCausalID

/-- Exact Boolean recovery from an observational profile. -/
def ExactBoolDecoder {World Observation : Type}
    (profile : World → Observation) (target : World → Bool) : Prop :=
  ∃ decoder : Observation → Bool,
    ∀ world, decoder (profile world) = target world

/-- Observational twins with different causal targets block exact identification. -/
theorem observational_twins_block_identification
    {World Observation : Type}
    (profile : World → Observation)
    (target : World → Bool)
    {left right : World}
    (hsame : profile left = profile right)
    (hdifferent : target left ≠ target right) :
    ¬ ExactBoolDecoder profile target := by
  intro hexact
  rcases hexact with ⟨decoder, hdecoder⟩
  apply hdifferent
  calc
    target left = decoder (profile left) := (hdecoder left).symm
    _ = decoder (profile right) := congrArg decoder hsame
    _ = target right := hdecoder right

/-- The backdoor control evaluates to three tenths under do(X=0). -/
theorem backdoor_low :
    (1 / 2 : ℚ) * (1 / 10 : ℚ) +
      (1 / 2 : ℚ) * (1 / 2 : ℚ) = 3 / 10 := by
  norm_num

/-- The backdoor control evaluates to seven tenths under do(X=1). -/
theorem backdoor_high :
    (1 / 2 : ℚ) * (1 / 2 : ℚ) +
      (1 / 2 : ℚ) * (9 / 10 : ℚ) = 7 / 10 := by
  norm_num

/-- The front-door inner standardization at mediator zero equals three tenths. -/
theorem frontdoor_inner_zero :
    (1 / 2 : ℚ) * (1 / 10 : ℚ) +
      (1 / 2 : ℚ) * (1 / 2 : ℚ) = 3 / 10 := by
  norm_num

/-- The front-door inner standardization at mediator one equals seven tenths. -/
theorem frontdoor_inner_one :
    (1 / 2 : ℚ) * (1 / 2 : ℚ) +
      (1 / 2 : ℚ) * (9 / 10 : ℚ) = 7 / 10 := by
  norm_num

/-- The front-door control evaluates to two fifths under do(X=0). -/
theorem frontdoor_low :
    (3 / 4 : ℚ) * (3 / 10 : ℚ) +
      (1 / 4 : ℚ) * (7 / 10 : ℚ) = 2 / 5 := by
  norm_num

/-- The front-door control evaluates to three fifths under do(X=1). -/
theorem frontdoor_high :
    (1 / 4 : ℚ) * (3 / 10 : ℚ) +
      (3 / 4 : ℚ) * (7 / 10 : ℚ) = 3 / 5 := by
  norm_num

/-- The identified front-door causal contrast is one fifth. -/
theorem frontdoor_effect :
    (3 / 5 : ℚ) - (2 / 5 : ℚ) = 1 / 5 := by
  norm_num

/-- The bow-arc twin models can have causal effects one and zero. -/
theorem bow_twin_effects_differ :
    (1 : ℚ) ≠ 0 := by
  norm_num

#print axioms FiniteCausalID.observational_twins_block_identification
#print axioms FiniteCausalID.backdoor_low
#print axioms FiniteCausalID.backdoor_high
#print axioms FiniteCausalID.frontdoor_inner_zero
#print axioms FiniteCausalID.frontdoor_inner_one
#print axioms FiniteCausalID.frontdoor_low
#print axioms FiniteCausalID.frontdoor_high
#print axioms FiniteCausalID.frontdoor_effect
#print axioms FiniteCausalID.bow_twin_effects_differ

end FiniteCausalID
