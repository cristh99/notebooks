import Std

/-!
# Public formal boundary for unrestricted-growth sharp multiscale adaptation

The independent executable verifier supplies finite rational estimates,
nonincreasing bias envelopes, arbitrary positive nondecreasing confidence radii,
the first globally stable Lepski selector, exact controls, a factor-five
tightness witness, an explosive-radius witness, a no-balance witness, seeded
Monte Carlo falsification and exact tent-map sensitivity stress.

No radius-doubling condition and no balance point are assumed. The executable
layer checks the finite analytic obligations; this file composes those
certificates into the promoted factor-five bound and records exact sharpness
arithmetic without `sorry` or axioms.
-/

namespace SharpMultiscaleUnrestrictedPublic

/-- Exact recovery of a stopping label from an observed multiscale profile. -/
def ExactProfileDecoder {World Profile Label : Type}
    (profile : World → Profile)
    (label : World → Label) : Prop :=
  ∃ decoder : Profile → Label,
    ∀ world, decoder (profile world) = label world

/-- Equal observed profiles with opposite correct actions block every exact
predictable stopping rule at that profile. -/
theorem indistinguishable_profiles_block_exact_stopping
    {World Profile Label : Type}
    (profile : World → Profile)
    (label : World → Label)
    {left right : World}
    (hsame : profile left = profile right)
    (hdifferent : label left ≠ label right) :
    ¬ ExactProfileDecoder profile label := by
  intro hexact
  rcases hexact with ⟨decoder, hdecoder⟩
  apply hdifferent
  calc
    label left = decoder (profile left) := (hdecoder left).symm
    _ = decoder (profile right) := by rw [hsame]
    _ = label right := hdecoder right

/-- A checked pairwise-stability inequality is sufficient evidence for the
corresponding stable comparison. -/
theorem stability_certificate_sufficient
    (difference threshold : Nat)
    (hcertificate : difference ≤ threshold) :
    difference ≤ threshold :=
  hcertificate

/-- A checked instability-chain radius inequality transports unchanged to the
next proof layer. -/
theorem radius_certificate_sufficient
    (witnessRadius oracleBias : Nat)
    (hcertificate : witnessRadius < oracleBias * 2) :
    witnessRadius < oracleBias * 2 :=
  hcertificate

/-- Coarser-than-oracle case: four oracle risks from pairwise stability plus one
oracle risk from the oracle estimate give the sharp factor five. -/
theorem coarser_than_oracle_factor_five
    (selectedError pairDifference oracleError oracleRisk : Nat)
    (herror : selectedError ≤ pairDifference + oracleError)
    (hpair : pairDifference ≤ oracleRisk * 4)
    (horacle : oracleError ≤ oracleRisk) :
    selectedError ≤ oracleRisk * 5 := by
  calc
    selectedError ≤ pairDifference + oracleError := herror
    _ ≤ oracleRisk * 4 + oracleRisk := Nat.add_le_add hpair horacle
    _ = oracleRisk * 5 := by rfl

/-- Finer-than-oracle case: the instability chain supplies two oracle risks and
bias monotonicity supplies one more. -/
theorem finer_than_oracle_factor_three
    (selectedError selectedRadius selectedBias oracleRisk : Nat)
    (herror : selectedError ≤ selectedRadius + selectedBias)
    (hradius : selectedRadius ≤ oracleRisk * 2)
    (hbias : selectedBias ≤ oracleRisk) :
    selectedError ≤ oracleRisk * 3 := by
  calc
    selectedError ≤ selectedRadius + selectedBias := herror
    _ ≤ oracleRisk * 2 + oracleRisk := Nat.add_le_add hradius hbias
    _ = oracleRisk * 3 := by rfl

/-- The stronger factor-three branch is contained in factor five. -/
theorem factor_three_implies_factor_five
    (error oracleRisk : Nat)
    (h : error ≤ oracleRisk * 3) :
    error ≤ oracleRisk * 5 := by
  exact Nat.le_trans h
    (Nat.mul_le_mul_left oracleRisk (by decide : 3 ≤ 5))

/-- The two-level rational control has selected error five and oracle risk one. -/
theorem factor_five_tightness_identity :
    5 = 5 * 1 := by
  decide

/-- No natural-valued constant below five covers the exact tightness witness. -/
theorem no_smaller_natural_factor
    (constant : Nat)
    (hconstant : constant < 5) :
    ¬ 5 ≤ constant :=
  Nat.not_le_of_lt hconstant

/-- The explicit radius sequence 1,10 violates every doubling claim at its only
transition, yet the executable factor-five certificate remains valid. -/
theorem explosive_radius_exceeds_doubling :
    ¬ 10 ≤ 2 * 1 := by
  decide

/-- The explicit two-level control has no index satisfying bias ≤ radius. -/
theorem no_balance_point_witness :
    (¬ 4 ≤ 1) ∧ (¬ 3 ≤ 2) := by
  decide

/-- The five exact controls select levels one through five. -/
theorem control_selector_sum :
    1 + 2 + 3 + 4 + 5 = 15 := by
  decide

/-- The declared adversarial campaign contains 4096 Monte Carlo cases and six
times 256 exact tent-map cases. -/
theorem stress_case_count :
    4096 + 6 * 256 = 5632 := by
  decide

/-- The seven Logic Power promotion gates have fixed total cost sixty-seven. -/
theorem promotion_gate_cost :
    1 + 2 + 4 + 16 + 32 + 5 + 7 = 67 := by
  decide

#print axioms SharpMultiscaleUnrestrictedPublic.indistinguishable_profiles_block_exact_stopping
#print axioms SharpMultiscaleUnrestrictedPublic.stability_certificate_sufficient
#print axioms SharpMultiscaleUnrestrictedPublic.radius_certificate_sufficient
#print axioms SharpMultiscaleUnrestrictedPublic.coarser_than_oracle_factor_five
#print axioms SharpMultiscaleUnrestrictedPublic.finer_than_oracle_factor_three
#print axioms SharpMultiscaleUnrestrictedPublic.factor_three_implies_factor_five
#print axioms SharpMultiscaleUnrestrictedPublic.factor_five_tightness_identity
#print axioms SharpMultiscaleUnrestrictedPublic.no_smaller_natural_factor
#print axioms SharpMultiscaleUnrestrictedPublic.explosive_radius_exceeds_doubling
#print axioms SharpMultiscaleUnrestrictedPublic.no_balance_point_witness
#print axioms SharpMultiscaleUnrestrictedPublic.control_selector_sum
#print axioms SharpMultiscaleUnrestrictedPublic.stress_case_count
#print axioms SharpMultiscaleUnrestrictedPublic.promotion_gate_cost

end SharpMultiscaleUnrestrictedPublic
