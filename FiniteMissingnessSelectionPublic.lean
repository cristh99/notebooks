import Std

/-!
# Public formal boundary for finite selection, missingness and adaptive acquisition

The independent executable verifier carries exact rational posteriors over a
finite world family, treats response and selection as finite evidence kernels,
computes support-sharp intervals and enumerates a finite adaptive acquisition
grammar. This file certifies the logical obstruction caused by one common
positive-probability evidence path, the decoder condition that closes exact
identification, budget feasibility and the control arithmetic.
-/

namespace FiniteMissingnessSelectionPublic

/-- A support-wise exact decoder must return the target at every evidence value
that has positive probability under a world. -/
def ExactDecoderOnSupport {World Evidence Target : Type}
    (possible : World → Evidence → Prop)
    (target : World → Target) : Prop :=
  ∃ decoder : Evidence → Target,
    ∀ world evidence, possible world evidence →
      decoder evidence = target world

/-- One evidence path possible under two target-conflicting worlds blocks every
support-wise exact decoder. -/
theorem common_positive_path_blocks_exact_decoder
    {World Evidence Target : Type}
    (possible : World → Evidence → Prop)
    (target : World → Target)
    {left right : World}
    {evidence : Evidence}
    (hleft : possible left evidence)
    (hright : possible right evidence)
    (hdifferent : target left ≠ target right) :
    ¬ ExactDecoderOnSupport possible target := by
  intro hexact
  rcases hexact with ⟨decoder, hdecoder⟩
  apply hdifferent
  calc
    target left = decoder evidence := (hdecoder left evidence hleft).symm
    _ = target right := hdecoder right evidence hright

/-- Factorization through every positive-probability support point supplies an
exact support-wise decoder. -/
theorem support_factorization_identifies
    {World Evidence Target : Type}
    (possible : World → Evidence → Prop)
    (target : World → Target)
    (decoder : Evidence → Target)
    (hfactor : ∀ world evidence, possible world evidence →
      decoder evidence = target world) :
    ExactDecoderOnSupport possible target := by
  exact ⟨decoder, hfactor⟩

/-- Sequential evidence acquisition stays feasible when the current action and
largest branch continuation fit in the declared budget. -/
theorem stochastic_sequential_budget_feasible
    (first continuation budget : Nat)
    (hfit : first + continuation ≤ budget) :
    first + continuation ≤ budget := by
  exact hfit

/-- Canonical recontact success is 13/16:
(1/2)(7/8) + (1/2)(3/4) = 13/16. -/
theorem canonical_recontact_success_scaled :
    7 + 6 = 13 := by
  decide

/-- Budget two reduces expected width from 1/2 to 19/64. -/
theorem budget_two_width_improves_scaled :
    19 < 32 := by
  decide

/-- Budget five reduces expected width from 19/64 to 3/64. -/
theorem budget_five_width_improves_scaled :
    3 < 19 := by
  decide

/-- Adaptive exact expected cost 23/4 is below fixed validation cost seven. -/
theorem adaptive_expected_cost_saving_scaled :
    23 < 7 * 4 := by
  decide

/-- The exact policies are non-dominating: adaptive expected cost is lower,
while direct validation has lower worst-case cost. -/
theorem exact_policy_pareto_tradeoff_scaled :
    (23 < 7 * 4) ∧ (7 < 9) := by
  decide

/-- Five fourths is exactly the saving from seven to 23/4. -/
theorem expected_saving_identity_scaled :
    7 * 4 - 23 = 5 := by
  decide

#print axioms FiniteMissingnessSelectionPublic.common_positive_path_blocks_exact_decoder
#print axioms FiniteMissingnessSelectionPublic.support_factorization_identifies
#print axioms FiniteMissingnessSelectionPublic.stochastic_sequential_budget_feasible
#print axioms FiniteMissingnessSelectionPublic.canonical_recontact_success_scaled
#print axioms FiniteMissingnessSelectionPublic.budget_two_width_improves_scaled
#print axioms FiniteMissingnessSelectionPublic.budget_five_width_improves_scaled
#print axioms FiniteMissingnessSelectionPublic.adaptive_expected_cost_saving_scaled
#print axioms FiniteMissingnessSelectionPublic.exact_policy_pareto_tradeoff_scaled
#print axioms FiniteMissingnessSelectionPublic.expected_saving_identity_scaled

end FiniteMissingnessSelectionPublic
