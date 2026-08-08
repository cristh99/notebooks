import Std

/-!
# Finite logical boundary for proof-carrying Blackwell comparison

The executable compiler supplies exact rational kernels, convex-hull replay and
separating decision witnesses. This file formalizes the order-theoretic
transport and exact cross-multiplied controls using Lean's standard library.
-/

namespace BlackwellFinite

/-- A decision witness with strictly larger target value refutes the claim that
all target decisions can be simulated without advantage from the source. -/
def NoTargetAdvantage
    {Decision Value : Type}
    (le : Value → Value → Prop)
    (sourceValue targetValue : Decision → Value) : Prop :=
  ∀ decision, le (targetValue decision) (sourceValue decision)

theorem strict_decision_witness_refutes_dominance
    {Decision Value : Type}
    (le : Value → Value → Prop)
    (sourceValue targetValue : Decision → Value)
    (decision : Decision)
    (strict : ¬ le (targetValue decision) (sourceValue decision)) :
    ¬ NoTargetAdvantage le sourceValue targetValue := by
  intro hall
  exact strict (hall decision)

/-- Any transitive experiment comparison remains transitive after two certified
simulation steps. -/
theorem dominance_transitive
    {Experiment : Type}
    (dominates : Experiment → Experiment → Prop)
    (htrans : ∀ {a b c},
      dominates a b → dominates b c → dominates a c)
    {source middle target : Experiment}
    (hsm : dominates source middle)
    (hmt : dominates middle target) :
    dominates source target := by
  exact htrans hsm hmt

/-- Cross-multiplied stochastic-row check: 3/4 + 1/4 = 1. -/
theorem quarter_noise_kernel_row_crosscheck :
    3 + 1 = 4 := by
  native_decide

/-- Composition check for the correct-output probability 5/8. -/
theorem quarter_noise_composition_diagonal_crosscheck :
    (3 * 3 + 1 * 1) * 8 = 5 * 16 := by
  native_decide

/-- Composition check for the error probability 3/8. -/
theorem quarter_noise_composition_offdiagonal_crosscheck :
    (3 * 1 + 1 * 3) * 8 = 3 * 16 := by
  native_decide

/-- The target decision value two exceeds the source optimum one by one. -/
theorem separating_decision_gap_crosscheck :
    (2 : Int) - 1 = 1 := by
  native_decide

/-- Four deterministic maps exist between two binary outcome spaces. -/
theorem binary_deterministic_garbling_count :
    2 ^ 2 = 4 := by
  native_decide

#print axioms BlackwellFinite.strict_decision_witness_refutes_dominance
#print axioms BlackwellFinite.dominance_transitive
#print axioms BlackwellFinite.quarter_noise_kernel_row_crosscheck
#print axioms BlackwellFinite.quarter_noise_composition_diagonal_crosscheck
#print axioms BlackwellFinite.quarter_noise_composition_offdiagonal_crosscheck
#print axioms BlackwellFinite.separating_decision_gap_crosscheck
#print axioms BlackwellFinite.binary_deterministic_garbling_count

end BlackwellFinite
