import Std

/-!
# Formal boundary for proof-carrying finite lower bounds

This file deliberately uses only Lean's standard library. The executable
compiler supplies the exact rational total-variation and risk calculations;
these theorems certify the logical transport from indistinguishability and
matching bounds to impossibility and optimality.
-/

namespace FiniteLowerBounds

/-- Exact recovery of a target from an observation profile. -/
def ExactTargetDecoder {World Observation Target : Type}
    (profile : World → Observation) (target : World → Target) : Prop :=
  ∃ decoder : Observation → Target,
    ∀ world, decoder (profile world) = target world

/-- Equal observations with different targets rule out exact recovery. -/
theorem indistinguishable_pair_no_exact_decoder
    {World Observation Target : Type}
    (profile : World → Observation) (target : World → Target)
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

/-- Four coordinatewise bounds combine under any binary monotone aggregator. -/
theorem four_coordinate_bounds_combine
    {Value : Type}
    (combine : Value → Value → Value)
    (le : Value → Value → Prop)
    (hmono : ∀ a b c d,
      le a b → le c d → le (combine a c) (combine b d))
    (l0 l1 l2 l3 r0 r1 r2 r3 : Value)
    (h0 : le l0 r0) (h1 : le l1 r1)
    (h2 : le l2 r2) (h3 : le l3 r3) :
    le (combine (combine l0 l1) (combine l2 l3))
      (combine (combine r0 r1) (combine r2 r3)) := by
  exact hmono _ _ _ _
    (hmono _ _ _ _ h0 h1)
    (hmono _ _ _ _ h2 h3)

/-- Matching universal lower and candidate upper bounds certify optimality. -/
theorem matching_bounds_certify_optimality
    {Procedure Value : Type}
    (le : Value → Value → Prop)
    (antisymm : ∀ {a b}, le a b → le b a → a = b)
    (risk : Procedure → Value)
    (candidate : Procedure)
    (bound : Value)
    (hlower : ∀ procedure, le bound (risk procedure))
    (hupper : le (risk candidate) bound) :
    risk candidate = bound ∧
      ∀ procedure, le (risk candidate) (risk procedure) := by
  have hcandidate : risk candidate = bound :=
    antisymm hupper (hlower candidate)
  constructor
  · exact hcandidate
  · intro procedure
    rw [hcandidate]
    exact hlower procedure

/-- A missing required coordinate is an instance of indistinguishability. -/
theorem missing_coordinate_blocks_exact_boolean_target
    {dimension : Nat}
    (observe : (Fin dimension → Bool) → (Fin dimension → Bool))
    (target : (Fin dimension → Bool) → Bool)
    (left right : Fin dimension → Bool)
    (hsame : observe left = observe right)
    (hdifferent : target left ≠ target right) :
    ¬ ExactTargetDecoder observe target :=
  indistinguishable_pair_no_exact_decoder
    observe target hsame hdifferent

#print axioms FiniteLowerBounds.indistinguishable_pair_no_exact_decoder
#print axioms FiniteLowerBounds.four_coordinate_bounds_combine
#print axioms FiniteLowerBounds.matching_bounds_certify_optimality
#print axioms FiniteLowerBounds.missing_coordinate_blocks_exact_boolean_target

end FiniteLowerBounds
