import Std

/-!
# Public formal boundary for sharp finite multiscale adaptation

The independent executable verifier supplies finite rational estimates,
nonincreasing bias envelopes, nondecreasing confidence radii with successive
ratio at most two, the first globally stable Lepski selector, exact controls,
a factor-five tightness witness, seeded Monte Carlo falsification and exact
tent-map sensitivity stress. This file certifies the deterministic inequality
skeleton and the arithmetic identities used by the public capsule. It does not
formalize a continuous minimax experiment or the stochastic origin of the
simultaneous event.
-/

namespace SharpMultiscaleAdaptationPublic

/-- Exact recovery of a stopping label from an observed multiscale prefix. -/
def ExactPrefixDecoder {World Prefix Label : Type}
    (prefix : World → Prefix)
    (label : World → Label) : Prop :=
  ∃ decoder : Prefix → Label,
    ∀ world, decoder (prefix world) = label world

/-- Equal observed prefixes with opposite correct actions block every exact
predictable stopping rule at that prefix. -/
theorem indistinguishable_prefix_blocks_exact_stopping
    {World Prefix Label : Type}
    (prefix : World → Prefix)
    (label : World → Label)
    {safe unsafe : World}
    (hsame : prefix safe = prefix unsafe)
    (hdifferent : label safe ≠ label unsafe) :
    ¬ ExactPrefixDecoder prefix label := by
  intro hexact
  rcases hexact with ⟨decoder, hdecoder⟩
  apply hdifferent
  calc
    label safe = decoder (prefix safe) := (hdecoder safe).symm
    _ = decoder (prefix unsafe) := by rw [hsame]
    _ = label unsafe := hdecoder unsafe

/-- At the first balanced level, the simultaneous event and monotonicity imply
stability against every finer level under threshold `2(r_k+r_l)`. -/
theorem balanced_pair_is_stable
    (difference bk rk bl rl : Nat)
    (hevent : difference ≤ bk + rk + bl + rl)
    (hbalance : bk ≤ rk)
    (hbias : bl ≤ bk)
    (hradius : rk ≤ rl) :
    difference ≤ 2 * (rk + rl) := by
  omega

/-- Instability of a coarse level against a finer witness forces the witness
radius below twice the coarse bias. -/
theorem instability_bounds_witness_radius
    (difference bk rk bl rl : Nat)
    (hunstable : 2 * (rk + rl) < difference)
    (hevent : difference ≤ bk + rk + bl + rl)
    (hbias : bl ≤ bk) :
    rl < 2 * bk := by
  omega

/-- If the selected stable level is coarser than the oracle, stability to the
oracle plus oracle coverage yields the sharp universal factor five. -/
theorem coarser_than_oracle_factor_five
    (selectedError pairDifference oracleError selectedRadius oracleRadius oracleRisk : Nat)
    (herror : selectedError ≤ pairDifference + oracleError)
    (hstable : pairDifference ≤ 2 * (selectedRadius + oracleRadius))
    (hradii : selectedRadius ≤ oracleRadius)
    (horacleRadius : oracleRadius ≤ oracleRisk)
    (horacleError : oracleError ≤ oracleRisk) :
    selectedError ≤ 5 * oracleRisk := by
  omega

/-- If selection is finer than the oracle, the instability chain bounds the
selected radius by twice the oracle bias, giving the stronger factor three. -/
theorem finer_than_oracle_factor_three
    (selectedError selectedBias selectedRadius oracleBias oracleRisk : Nat)
    (herror : selectedError ≤ selectedBias + selectedRadius)
    (hbias : selectedBias ≤ oracleBias)
    (hradius : selectedRadius < 2 * oracleBias)
    (horacle : oracleBias ≤ oracleRisk) :
    selectedError ≤ 3 * oracleRisk := by
  omega

/-- Factor three lies inside the promoted factor-five envelope. -/
theorem factor_three_implies_factor_five
    (error oracleRisk : Nat)
    (h : error ≤ 3 * oracleRisk) :
    error ≤ 5 * oracleRisk := by
  omega

/-- The two-level rational control has selected error five and oracle risk one. -/
theorem factor_five_tightness_identity :
    5 = 5 * 1 := by
  decide

/-- No natural-valued constant below five covers the exact tightness witness. -/
theorem no_smaller_natural_factor
    (constant : Nat)
    (hconstant : constant < 5) :
    ¬ 5 ≤ constant * 1 := by
  omega

/-- The five exact controls select levels one through five. -/
theorem control_selector_sum :
    1 + 2 + 3 + 4 + 5 = 15 := by
  decide

/-- The declared adversarial campaign contains 4096 Monte Carlo cases and
five times 256 exact tent-map cases. -/
theorem stress_case_count :
    4096 + 5 * 256 = 5376 := by
  decide

/-- The eight Logic Power promotion gates have fixed total cost seventy-five. -/
theorem promotion_gate_cost :
    1 + 2 + 4 + 8 + 16 + 32 + 5 + 7 = 75 := by
  decide

#print axioms SharpMultiscaleAdaptationPublic.indistinguishable_prefix_blocks_exact_stopping
#print axioms SharpMultiscaleAdaptationPublic.balanced_pair_is_stable
#print axioms SharpMultiscaleAdaptationPublic.instability_bounds_witness_radius
#print axioms SharpMultiscaleAdaptationPublic.coarser_than_oracle_factor_five
#print axioms SharpMultiscaleAdaptationPublic.finer_than_oracle_factor_three
#print axioms SharpMultiscaleAdaptationPublic.factor_three_implies_factor_five
#print axioms SharpMultiscaleAdaptationPublic.factor_five_tightness_identity
#print axioms SharpMultiscaleAdaptationPublic.no_smaller_natural_factor
#print axioms SharpMultiscaleAdaptationPublic.control_selector_sum
#print axioms SharpMultiscaleAdaptationPublic.stress_case_count
#print axioms SharpMultiscaleAdaptationPublic.promotion_gate_cost

end SharpMultiscaleAdaptationPublic
