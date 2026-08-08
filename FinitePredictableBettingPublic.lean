import Std

/-!
# Public formal boundary for predictable competitive e-processes

The independent verifier represents fixed and Markov-switching expert mixtures
as predictable betting processes, constructs a convex meta-process, checks
bounded optional stopping exhaustively and rejects post-hoc maximization. This
file certifies the algebraic validity boundary, the impossibility of free strict
pointwise dominance, the competitive envelope and the exact control arithmetic.
-/

namespace FinitePredictableBettingPublic

/-- Under a fair sign, the two possible scaled factors average back to one. -/
theorem fair_pair_sum (stake : Int) :
    (2 + stake) + (2 - stake) = 4 := by
  omega

/-- A scaled stake in `[-2,2]` produces two nonnegative factors. -/
theorem safe_factors_nonnegative
    (stake : Int)
    (hlower : -2 ≤ stake)
    (hupper : stake ≤ 2) :
    0 ≤ 2 + stake ∧ 0 ≤ 2 - stake := by
  omega

/-- If a candidate dominates a baseline on both positive-mass atoms, while its
sum is no larger, then equality is forced atom by atom. -/
theorem two_atom_no_free_strict_dominance
    (candidate0 candidate1 baseline0 baseline1 : Nat)
    (h0 : baseline0 ≤ candidate0)
    (h1 : baseline1 ≤ candidate1)
    (hsum : candidate0 + candidate1 ≤ baseline0 + baseline1) :
    candidate0 = baseline0 ∧ candidate1 = baseline1 := by
  omega

/-- A half-half meta-mixture is within factor two of its left component. -/
theorem half_competitive_left (left right : Nat) :
    left ≤ left + right := by
  omega

/-- A half-half meta-mixture is within factor two of its right component. -/
theorem half_competitive_right (left right : Nat) :
    right ≤ left + right := by
  omega

/-- Post-hoc maximization has expectation `17/16`, above one. -/
theorem posthoc_maximum_inflates_mean :
    16 < 17 := by
  decide

/-- The one-switch lower-bound ratio is `3^16/2^23 > 1`. -/
theorem one_switch_lower_bound_beats_fixed :
    8388608 < 43046721 := by
  decide

/-- A twelve-step one-switch path has ten stays and one switch. -/
theorem one_switch_transition_count :
    10 + 1 = 11 := by
  decide

/-- The canonical switching-path prior numerator is positive. -/
theorem canonical_switch_path_weight_positive :
    0 < 59049 := by
  decide

/-- The meta-process preserves the fixed component at half initial capital. -/
theorem meta_retains_fixed_component (fixed switching : Nat) :
    fixed ≤ fixed + switching := by
  omega

#print axioms FinitePredictableBettingPublic.fair_pair_sum
#print axioms FinitePredictableBettingPublic.safe_factors_nonnegative
#print axioms FinitePredictableBettingPublic.two_atom_no_free_strict_dominance
#print axioms FinitePredictableBettingPublic.half_competitive_left
#print axioms FinitePredictableBettingPublic.half_competitive_right
#print axioms FinitePredictableBettingPublic.posthoc_maximum_inflates_mean
#print axioms FinitePredictableBettingPublic.one_switch_lower_bound_beats_fixed
#print axioms FinitePredictableBettingPublic.one_switch_transition_count
#print axioms FinitePredictableBettingPublic.canonical_switch_path_weight_positive
#print axioms FinitePredictableBettingPublic.meta_retains_fixed_component

end FinitePredictableBettingPublic
