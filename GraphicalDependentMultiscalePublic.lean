import Std

/-!
# Formal boundary for finite graphical dependent multiscale inference

The executable compiler enumerates finite rational Bayesian networks in declared
topological order, preserves cross-scale and cross-cluster dependence represented
by the graph, optimizes simultaneous radii and transports the event into the
factor-five multiscale guarantee.  This file records the logical obstruction
from marginal indistinguishability, probability-mass transport and exact control
arithmetic.  It does not formalize measure theory or infer the graph from data.
-/

namespace GraphicalDependentMultiscalePublic

/-- Exact calibration from a declared evidence summary. -/
def ExactCalibrationDecoder {World Evidence Calibration : Type}
    (evidence : World → Evidence)
    (calibration : World → Calibration) : Prop :=
  ∃ decoder : Evidence → Calibration,
    ∀ world, decoder (evidence world) = calibration world

/-- Identical marginal evidence with different valid simultaneous calibrations
blocks every exact marginal-only calibration rule. -/
theorem equal_marginals_block_exact_calibration
    {World Evidence Calibration : Type}
    (evidence : World → Evidence)
    (calibration : World → Calibration)
    {independent dependent : World}
    (hsame : evidence independent = evidence dependent)
    (hdifferent : calibration independent ≠ calibration dependent) :
    ¬ ExactCalibrationDecoder evidence calibration := by
  intro hexact
  rcases hexact with ⟨decoder, hdecoder⟩
  apply hdifferent
  calc
    calibration independent = decoder (evidence independent) :=
      (hdecoder independent).symm
    _ = decoder (evidence dependent) := by rw [hsame]
    _ = calibration dependent := hdecoder dependent

/-- If the simultaneous event has enough probability and is contained in the
factor-five guarantee, the guarantee inherits that probability. -/
theorem event_mass_transports_to_guarantee
    (requiredMass eventMass guaranteeMass : Nat)
    (hcoverage : requiredMass ≤ eventMass)
    (hsubset : eventMass ≤ guaranteeMass) :
    requiredMass ≤ guaranteeMass :=
  Nat.le_trans hcoverage hsubset

/-- One binary latent state and eight four-state clusters yield 2·4^8 complete
assignments. -/
theorem canonical_graphical_assignment_count :
    2 * 4 ^ 8 = 131072 := by
  decide

/-- The exact graphical convolution collapses the assignments to 81 states. -/
theorem canonical_graphical_state_count :
    9 * 9 = 81 := by
  decide

/-- Marginally calibrated radii undercover under the common-latent truth. -/
theorem marginal_calibration_undercoverage :
    20 * 1018398879 < 19 * 1073741824 := by
  decide

/-- Graph-aware radii exceed the required nineteen-twentieths mass. -/
theorem graphical_calibration_reaches_target :
    19 * 2147483648 ≤ 20 * 2040535305 := by
  decide

/-- Converting the naive mass to the common denominator shows exact recovery
of 3,737,547 probability units. -/
theorem graphical_coverage_recovery_identity :
    2040535305 - 2 * 1018398879 = 3737547 := by
  decide

/-- Marginal-independence radii sum to 57/64. -/
theorem naive_radius_sum_scaled :
    3 + 6 + 10 + 14 + 24 = 57 := by
  decide

/-- Graph-aware radii sum to 60/64. -/
theorem graphical_radius_sum_scaled :
    4 + 8 + 10 + 14 + 24 = 60 := by
  decide

/-- Bonferroni radii sum to 69/64. -/
theorem bonferroni_radius_sum_scaled :
    3 + 6 + 12 + 18 + 30 = 69 := by
  decide

/-- The latent mixture gives E[Z_i Z_j]=9/16 and E[Z_i]E[Z_j]=4/16,
so the cross-cluster covariance is 5/16. -/
theorem common_latent_covariance_scaled :
    9 - 4 = 5 := by
  decide

/-- Ten conjunctive promotion gates create 1024 latent defect worlds, of which
1023 conflict with the unique clean world. -/
theorem logic_power_gate_counts :
    (2 ^ 10 = 1024) ∧ (1024 - 1 = 1023) := by
  decide

/-- The ten fixed gate costs total 95. -/
theorem logic_power_fixed_cost :
    1 + 2 + 4 + 8 + 16 + 32 + 5 + 7 + 9 + 11 = 95 := by
  decide

#print axioms GraphicalDependentMultiscalePublic.equal_marginals_block_exact_calibration
#print axioms GraphicalDependentMultiscalePublic.event_mass_transports_to_guarantee
#print axioms GraphicalDependentMultiscalePublic.canonical_graphical_assignment_count
#print axioms GraphicalDependentMultiscalePublic.canonical_graphical_state_count
#print axioms GraphicalDependentMultiscalePublic.marginal_calibration_undercoverage
#print axioms GraphicalDependentMultiscalePublic.graphical_calibration_reaches_target
#print axioms GraphicalDependentMultiscalePublic.graphical_coverage_recovery_identity
#print axioms GraphicalDependentMultiscalePublic.naive_radius_sum_scaled
#print axioms GraphicalDependentMultiscalePublic.graphical_radius_sum_scaled
#print axioms GraphicalDependentMultiscalePublic.bonferroni_radius_sum_scaled
#print axioms GraphicalDependentMultiscalePublic.common_latent_covariance_scaled
#print axioms GraphicalDependentMultiscalePublic.logic_power_gate_counts
#print axioms GraphicalDependentMultiscalePublic.logic_power_fixed_cost

end GraphicalDependentMultiscalePublic
