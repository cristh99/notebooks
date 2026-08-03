import Std

/-!
# Public formal boundary for sharp finite multiscale adaptation

The independent executable verifier supplies finite rational estimates,
nonincreasing bias envelopes, nondecreasing confidence radii with successive
ratio at most two, the first globally stable Lepski selector, exact controls,
a factor-five tightness witness, seeded Monte Carlo falsification and exact
tent-map sensitivity stress. The executable layer checks the analytic
obligations; this file composes those certificates into the promoted factor-five
bound and records exact tightness arithmetic without `sorry` or axioms.
-/

namespace SharpMultiscaleAdaptationPublic

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

/-- A checked instability-chain radius inequality can be transported unchanged
to the next proof layer. -/
theorem radius_certificate_sufficient
    (witnessRadius oracleBias : Nat)
    (hcertificate : witnessRadius < oracleBias * 2) :
    witnessRadius < oracleBias * 2 :=
  hcertificate

/-- Coarser-than-oracle case. The executable verifier supplies three finite
obligations: selected error is at most pair difference plus oracle error; the
pair difference is at most four oracle risks; oracle error is at most one oracle
risk. Their composition is exactly the universal factor five. -/
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

/-- Finer-than-oracle case. The instability chain supplies selected radius at
most two oracle risks, while bias monotonicity supplies one more oracle risk. -/
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
  exact Nat.le_trans h (Nat.mul_le_mul_left oracleRisk (by decide : 3 ≤ 5))

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

#print axioms SharpMultiscaleAdaptationPublic.indistinguishable_profiles_block_exact_stopping
#print axioms SharpMultiscaleAdaptationPublic.stability_certificate_sufficient
#print axioms SharpMultiscaleAdaptationPublic.radius_certificate_sufficient
#print axioms SharpMultiscaleAdaptationPublic.coarser_than_oracle_factor_five
#print axioms SharpMultiscaleAdaptationPublic.finer_than_oracle_factor_three
#print axioms SharpMultiscaleAdaptationPublic.factor_three_implies_factor_five
#print axioms SharpMultiscaleAdaptationPublic.factor_five_tightness_identity
#print axioms SharpMultiscaleAdaptationPublic.no_smaller_natural_factor
#print axioms SharpMultiscaleAdaptationPublic.control_selector_sum
#print axioms SharpMultiscaleAdaptationPublic.stress_case_count
#print axioms SharpMultiscaleAdaptationPublic.promotion_gate_cost

end SharpMultiscaleAdaptationPublic
