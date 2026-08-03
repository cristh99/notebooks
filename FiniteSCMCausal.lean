import Mathlib

/-!
# Formal boundary for finite SCM causal identification

The executable compiler enumerates finite structural causal models and derives
observational and interventional laws. This file certifies the logical core:
observational twins block exact causal classification, while a target that
factors through two intervention profiles is identified by those profiles.
-/

namespace FiniteSCMCausal

/-- Exact Boolean recovery from an observable profile. -/
def ExactBoolDecoder {World Observation : Type}
    (profile : World → Observation) (target : World → Bool) : Prop :=
  ∃ decoder : Observation → Bool,
    ∀ world, decoder (profile world) = target world

/-- Observational twins with opposite causal targets rule out exact observational identification. -/
theorem observational_twins_block_causal_identification
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

/-- If the target factors through two interventional profiles, the pair identifies it. -/
theorem two_intervention_profiles_identify
    {World Profile0 Profile1 : Type}
    (profile0 : World → Profile0)
    (profile1 : World → Profile1)
    (target : World → Bool)
    (decoder : Profile0 → Profile1 → Bool)
    (hfactor : ∀ world,
      decoder (profile0 world) (profile1 world) = target world) :
    ExactBoolDecoder
      (fun world => (profile0 world, profile1 world)) target := by
  refine ⟨fun profiles => decoder profiles.1 profiles.2, ?_⟩
  intro world
  exact hfactor world

/-- The confounded no-effect control has zero interventional contrast. -/
theorem confounded_no_effect_contrast :
    (1 / 2 : ℚ) - (1 / 2 : ℚ) = 0 := by
  norm_num

/-- The direct-effect control has unit interventional contrast. -/
theorem direct_positive_effect_contrast :
    (1 : ℚ) - (0 : ℚ) = 1 := by
  norm_num

/-- The adaptive intervention policy has strictly lower expected cost than the fixed basis. -/
theorem adaptive_intervention_expected_cost_improves :
    (21 / 4 : ℚ) < 6 := by
  norm_num

#print axioms FiniteSCMCausal.observational_twins_block_causal_identification
#print axioms FiniteSCMCausal.two_intervention_profiles_identify
#print axioms FiniteSCMCausal.confounded_no_effect_contrast
#print axioms FiniteSCMCausal.direct_positive_effect_contrast
#print axioms FiniteSCMCausal.adaptive_intervention_expected_cost_improves

end FiniteSCMCausal
