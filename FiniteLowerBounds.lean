import Std

namespace FiniteLowerBounds

def ExactTargetDecoder {World Observation Target : Type}
    (profile : World → Observation) (target : World → Target) : Prop :=
  ∃ decoder : Observation → Target, ∀ world, decoder (profile world) = target world

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

theorem sum_coordinate_bounds
    {dimension : Nat}
    (lower risk : Fin dimension → Nat)
    (hcoordinate : ∀ coordinate, lower coordinate ≤ risk coordinate) :
    (Finset.univ.sum lower) ≤ Finset.univ.sum risk := by
  exact Finset.sum_le_sum fun coordinate _ => hcoordinate coordinate

theorem matching_bounds_certify_optimality
    {Procedure Value : Type}
    [PartialOrder Value]
    (risk : Procedure → Value)
    (candidate : Procedure)
    (bound : Value)
    (hlower : ∀ procedure, bound ≤ risk procedure)
    (hupper : risk candidate ≤ bound) :
    risk candidate = bound ∧
      ∀ procedure, risk candidate ≤ risk procedure := by
  have hcandidate : risk candidate = bound :=
    le_antisymm hupper (hlower candidate)
  constructor
  · exact hcandidate
  · intro procedure
    calc
      risk candidate = bound := hcandidate
      _ ≤ risk procedure := hlower procedure

#print axioms FiniteLowerBounds.indistinguishable_pair_no_exact_decoder
#print axioms FiniteLowerBounds.sum_coordinate_bounds
#print axioms FiniteLowerBounds.matching_bounds_certify_optimality

end FiniteLowerBounds
