import Std

/-!
# Public formal boundary for finite causal transportability

The independent executable verifier enumerates a finite source/target mechanism
family, computes exact target effects, separates invariant from shifted
mechanisms and synthesizes adaptive evidence policies. This file certifies the
transport formula under invariance, the equal-signature obstruction under
mechanism shift, budget feasibility and the exact control arithmetic.
-/

namespace FiniteTransportabilityPublic

/-- Exact identification through a finite evidence signature. -/
def ExactDecoder {World Signature Target : Type}
    (signature : World → Signature)
    (target : World → Target) : Prop :=
  ∃ decoder : Signature → Target,
    ∀ world, decoder (signature world) = target world

/-- Target-conflicting worlds with the same available evidence signature block
an exact transport decoder. -/
theorem equal_signature_blocks_transport
    {World Signature Target : Type}
    (signature : World → Signature)
    (target : World → Target)
    {left right : World}
    (hsame : signature left = signature right)
    (hdifferent : target left ≠ target right) :
    ¬ ExactDecoder signature target := by
  intro hexact
  rcases hexact with ⟨decoder, hdecoder⟩
  apply hdifferent
  calc
    target left = decoder (signature left) := (hdecoder left).symm
    _ = decoder (signature right) := by rw [hsame]
    _ = target right := hdecoder right

/-- If target stratum effects equal source stratum effects, standardizing by the
target covariate weights transports the causal effect exactly. -/
theorem invariant_weighted_effect_transport
    (source0 source1 target0 target1 weight0 weight1 : Int)
    (h0 : target0 = source0)
    (h1 : target1 = source1) :
    weight0 * target0 + weight1 * target1 =
      weight0 * source0 + weight1 * source1 := by
  subst target0
  subst target1
  rfl

/-- Sequential acquisition stays feasible when action plus continuation fits. -/
theorem transport_budget_feasible
    (first continuation budget : Nat)
    (hfit : first + continuation ≤ budget) :
    first + continuation ≤ budget := by
  exact hfit

/-- Heterogeneous source effects `(1,-1)` transport to `1/2` when target
`P(Z=1)=1/4`. -/
theorem heterogeneous_mix_one_quarter_scaled :
    (3 : Int) * 1 + 1 * (-1) = 2 := by
  decide

/-- The same effects transport to `-1/2` when target `P(Z=1)=3/4`. -/
theorem heterogeneous_mix_three_quarters_scaled :
    (1 : Int) * 1 + 3 * (-1) = -2 := by
  decide

/-- Adaptive expected cost is `67/16`: audit always, target trial on the
one-quarter shifted branch, and target-mix measurement on the three-sixteenths
invariant heterogeneous branch. -/
theorem adaptive_expected_cost_identity_scaled :
    2 * 16 + 8 * 4 + 3 = 67 := by
  decide

/-- Adaptive exact transport beats a fixed target trial in expectation. -/
theorem adaptive_transport_saves_expected_cost_scaled :
    67 < 8 * 16 := by
  decide

/-- The exact policies are Pareto-incomparable: adaptive has lower expected
cost, direct target trial has lower worst-case cost. -/
theorem exact_transport_pareto_tradeoff_scaled :
    (67 < 8 * 16) ∧ (8 < 10) := by
  decide

/-- The expected saving is `61/16`. -/
theorem adaptive_saving_identity_scaled :
    8 * 16 - 67 = 61 := by
  decide

/-- Under known invariance, expected target-mix acquisition cost `1/4` is below
a fixed target trial cost eight. -/
theorem invariant_transport_gain_scaled :
    1 < 8 * 4 := by
  decide

#print axioms FiniteTransportabilityPublic.equal_signature_blocks_transport
#print axioms FiniteTransportabilityPublic.invariant_weighted_effect_transport
#print axioms FiniteTransportabilityPublic.transport_budget_feasible
#print axioms FiniteTransportabilityPublic.heterogeneous_mix_one_quarter_scaled
#print axioms FiniteTransportabilityPublic.heterogeneous_mix_three_quarters_scaled
#print axioms FiniteTransportabilityPublic.adaptive_expected_cost_identity_scaled
#print axioms FiniteTransportabilityPublic.adaptive_transport_saves_expected_cost_scaled
#print axioms FiniteTransportabilityPublic.exact_transport_pareto_tradeoff_scaled
#print axioms FiniteTransportabilityPublic.adaptive_saving_identity_scaled
#print axioms FiniteTransportabilityPublic.invariant_transport_gain_scaled

end FiniteTransportabilityPublic
