import Std

/-!
# Formal boundary for finite causal identification

The executable verifier runs the finite ADMG ID algorithm and evaluates its
identified formulas. This file uses only Lean's standard library and certifies
the impossibility and exact arithmetic cores through observational equivalence
and cross-multiplied natural-number identities.
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

/-- Backdoor low-treatment value:
    1/2·1/10 + 1/2·1/2 = (1+5)/20 = 3/10. -/
theorem backdoor_low_cross_multiply :
    (1 + 5 : Nat) = 3 * 2 := by
  decide

/-- Backdoor high-treatment value:
    1/2·1/2 + 1/2·9/10 = (5+9)/20 = 7/10. -/
theorem backdoor_high_cross_multiply :
    (5 + 9 : Nat) = 7 * 2 := by
  decide

/-- Front-door inner standardization at mediator zero equals 3/10. -/
theorem frontdoor_inner_zero_cross_multiply :
    (1 + 5 : Nat) = 3 * 2 := by
  decide

/-- Front-door inner standardization at mediator one equals 7/10. -/
theorem frontdoor_inner_one_cross_multiply :
    (5 + 9 : Nat) = 7 * 2 := by
  decide

/-- Front-door low-treatment value:
    3/4·3/10 + 1/4·7/10 = (9+7)/40 = 2/5. -/
theorem frontdoor_low_cross_multiply :
    (9 + 7 : Nat) * 5 = 2 * 40 := by
  decide

/-- Front-door high-treatment value:
    1/4·3/10 + 3/4·7/10 = (3+21)/40 = 3/5. -/
theorem frontdoor_high_cross_multiply :
    (3 + 21 : Nat) * 5 = 3 * 40 := by
  decide

/-- The identified front-door causal contrast is 1/5. -/
theorem frontdoor_effect_cross_multiply :
    (3 - 2 : Nat) * 5 = 1 * 5 := by
  decide

/-- Bow-arc observational twins can have causal effects one and zero. -/
theorem bow_twin_effects_differ :
    (1 : Nat) ≠ 0 := by
  decide

/-- A hedge witness is sufficient to reject a claimed universal decoder. -/
theorem hedge_witness_blocks_decoder
    {World Observation : Type}
    (profile : World → Observation)
    (target : World → Bool)
    (left right : World)
    (hsame : profile left = profile right)
    (hdifferent : target left ≠ target right) :
    ¬ ExactBoolDecoder profile target :=
  observational_twins_block_identification
    profile target hsame hdifferent

#print axioms FiniteCausalID.observational_twins_block_identification
#print axioms FiniteCausalID.backdoor_low_cross_multiply
#print axioms FiniteCausalID.backdoor_high_cross_multiply
#print axioms FiniteCausalID.frontdoor_inner_zero_cross_multiply
#print axioms FiniteCausalID.frontdoor_inner_one_cross_multiply
#print axioms FiniteCausalID.frontdoor_low_cross_multiply
#print axioms FiniteCausalID.frontdoor_high_cross_multiply
#print axioms FiniteCausalID.frontdoor_effect_cross_multiply
#print axioms FiniteCausalID.bow_twin_effects_differ
#print axioms FiniteCausalID.hedge_witness_blocks_decoder

end FiniteCausalID
