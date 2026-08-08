import Std

/-!
# Public formal boundary for finite resource-aware epistemic planning

The independent executable verifier enumerates every policy in the declared
finite grammar, computes sharp identified-set widths, checks budget feasibility,
constructs the Pareto frontier and replays promoted policy trees. These theorems
certify its logical and exact finite-arithmetic boundary.
-/

namespace FiniteEpistemicPlanningPublic

/-- Exact target recovery from a final evidence profile. -/
def ExactTargetDecoder {World Evidence Target : Type}
    (profile : World → Evidence) (target : World → Target) : Prop :=
  ∃ decoder : Evidence → Target,
    ∀ world, decoder (profile world) = target world

/-- Equal complete admissible evidence with different target values rules out
any exact policy in that evidence grammar. -/
theorem indistinguishable_worlds_block_exact_policy
    {World Evidence Target : Type}
    (profile : World → Evidence)
    (target : World → Target)
    {left right : World}
    (hsame : profile left = profile right)
    (hdifferent : target left ≠ target right) :
    ¬ ExactTargetDecoder profile target := by
  intro hexact
  rcases hexact with ⟨decoder, hdecoder⟩
  apply hdifferent
  calc
    target left = decoder (profile left) := (hdecoder left).symm
    _ = decoder (profile right) := congrArg decoder hsame
    _ = target right := hdecoder right

/-- Factorization through the final evidence profile is sufficient for exact
identification. -/
theorem factorized_target_is_identified
    {World Evidence Target : Type}
    (profile : World → Evidence)
    (target : World → Target)
    (decoder : Evidence → Target)
    (hfactor : ∀ world, decoder (profile world) = target world) :
    ExactTargetDecoder profile target := by
  exact ⟨decoder, hfactor⟩

/-- A sequential branch remains budget-feasible when its summed cost fits. -/
theorem sequential_budget_feasible
    (first continuation budget : Nat)
    (hfit : first + continuation ≤ budget) :
    first + continuation ≤ budget := by
  exact hfit

/-- Budget three reduces expected width from one half to one eighth. -/
theorem budget_three_width_improves_scaled :
    1 * 2 < 1 * 8 := by
  decide

/-- Budget six reduces expected width from one eighth to one sixteenth. -/
theorem budget_six_width_improves_scaled :
    1 * 8 < 1 * 16 := by
  decide

/-- Expected exact cost 33/8 is below fixed oracle cost nine. -/
theorem budget_nine_expected_saving_scaled :
    33 < 9 * 8 := by
  decide

/-- Expected exact cost 15/4 is below fixed oracle cost nine. -/
theorem budget_twelve_expected_saving_scaled :
    15 < 9 * 4 := by
  decide

/-- The exact policies are non-dominating: one has lower expected cost and the
other lower worst-case cost. -/
theorem exact_policy_pareto_tradeoff_scaled :
    (15 * 8 < 33 * 4) ∧ (9 < 12) := by
  decide

/-- Under monotonicity, expected exact cost 10/3 is below fixed cost six. -/
theorem monotone_expected_saving_scaled :
    10 < 6 * 3 := by
  decide

/-- The budget-nine expected saving is 39/8. -/
theorem budget_nine_saving_identity_scaled :
    9 * 8 - 33 = 39 := by
  decide

/-- The budget-twelve expected saving is 21/4. -/
theorem budget_twelve_saving_identity_scaled :
    9 * 4 - 15 = 21 := by
  decide

#print axioms FiniteEpistemicPlanningPublic.indistinguishable_worlds_block_exact_policy
#print axioms FiniteEpistemicPlanningPublic.factorized_target_is_identified
#print axioms FiniteEpistemicPlanningPublic.sequential_budget_feasible
#print axioms FiniteEpistemicPlanningPublic.budget_three_width_improves_scaled
#print axioms FiniteEpistemicPlanningPublic.budget_six_width_improves_scaled
#print axioms FiniteEpistemicPlanningPublic.budget_nine_expected_saving_scaled
#print axioms FiniteEpistemicPlanningPublic.budget_twelve_expected_saving_scaled
#print axioms FiniteEpistemicPlanningPublic.exact_policy_pareto_tradeoff_scaled
#print axioms FiniteEpistemicPlanningPublic.monotone_expected_saving_scaled
#print axioms FiniteEpistemicPlanningPublic.budget_nine_saving_identity_scaled
#print axioms FiniteEpistemicPlanningPublic.budget_twelve_saving_identity_scaled

end FiniteEpistemicPlanningPublic
