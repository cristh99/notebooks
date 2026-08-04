import Std

/-!
# Formal boundary for cluster-dependent multiscale inference

The executable layer enumerates a finite exact cluster law, preserves arbitrary
within-cluster cross-scale dependence, convolves independent clusters, searches
simultaneous radii, and transports the resulting event into the sharp
factor-five Lepski guarantee.  This file records the generic probability-mass
transport and the exact cleared-denominator arithmetic of the canonical control.
It does not formalize measure theory or derive cluster independence.
-/

namespace ClusterDependentMultiscalePublic

/-- If an event has at least the required mass and every event outcome satisfies
the target guarantee, then the guarantee has at least the required mass.  In a
finite model the subset implication is represented by `eventMass ≤ guaranteeMass`.
-/
theorem event_mass_transports_to_guarantee
    (requiredMass eventMass guaranteeMass : Nat)
    (hcoverage : requiredMass ≤ eventMass)
    (hsubset : eventMass ≤ guaranteeMass) :
    requiredMass ≤ guaranteeMass :=
  Nat.le_trans hcoverage hsubset

/-- Eight four-outcome clusters create 4^8 raw paths. -/
theorem canonical_raw_path_count :
    4 ^ 8 = 65536 := by
  decide

/-- The exact convolution collapses the canonical 65,536 paths to 81 states. -/
theorem canonical_convolution_state_count :
    9 * 9 = 81 := by
  decide

/-- Exact simultaneous mass 4004639/4194304 exceeds 19/20. -/
theorem canonical_joint_coverage_exceeds_nineteen_twentieths :
    19 * 4194304 ≤ 20 * 4004639 := by
  decide

/-- Jointly optimized radii sum to 57/64. -/
theorem joint_radius_sum_scaled :
    3 + 6 + 10 + 14 + 24 = 57 := by
  decide

/-- Bonferroni radii sum to 69/64. -/
theorem bonferroni_radius_sum_scaled :
    3 + 6 + 12 + 18 + 30 = 69 := by
  decide

/-- Joint optimization removes 12/64 = 3/16 of total radius. -/
theorem total_radius_gain_scaled :
    69 - 57 = 12 := by
  decide

/-- Oracle risk drops from 10/32 to 9/32, a relative reduction of 1/10. -/
theorem oracle_risk_gain_scaled :
    (10 - 9 = 1) ∧ (1 * 10 = 10) := by
  decide

/-- The latent same-sign versus opposite-sign probabilities yield covariance
one half after centering: ((6-2)/8)=1/2. -/
theorem latent_covariance_half_scaled :
    (((6 : Int) - 2) * 2 = 8) := by
  decide

/-- In the nonvacuous bridge control, guarantee mass 31/32 and violation mass
1/32 partition the finite law. -/
theorem bridge_mass_partition :
    31 + 1 = 32 := by
  decide

/-- The bridge event itself reaches the declared 31/32 threshold. -/
theorem bridge_event_reaches_threshold :
    31 ≤ 31 := by
  decide

/-- Nine conjunctive promotion gates generate 512 latent defect worlds and 511
worlds conflict with the unique clean world. -/
theorem logic_power_gate_counts :
    (2 ^ 9 = 512) ∧ (512 - 1 = 511) := by
  decide

/-- The nine fixed gate costs total 84. -/
theorem logic_power_fixed_cost :
    1 + 2 + 4 + 8 + 16 + 32 + 5 + 7 + 9 = 84 := by
  decide

#print axioms ClusterDependentMultiscalePublic.event_mass_transports_to_guarantee
#print axioms ClusterDependentMultiscalePublic.canonical_raw_path_count
#print axioms ClusterDependentMultiscalePublic.canonical_convolution_state_count
#print axioms ClusterDependentMultiscalePublic.canonical_joint_coverage_exceeds_nineteen_twentieths
#print axioms ClusterDependentMultiscalePublic.joint_radius_sum_scaled
#print axioms ClusterDependentMultiscalePublic.bonferroni_radius_sum_scaled
#print axioms ClusterDependentMultiscalePublic.total_radius_gain_scaled
#print axioms ClusterDependentMultiscalePublic.oracle_risk_gain_scaled
#print axioms ClusterDependentMultiscalePublic.latent_covariance_half_scaled
#print axioms ClusterDependentMultiscalePublic.bridge_mass_partition
#print axioms ClusterDependentMultiscalePublic.bridge_event_reaches_threshold
#print axioms ClusterDependentMultiscalePublic.logic_power_gate_counts
#print axioms ClusterDependentMultiscalePublic.logic_power_fixed_cost

end ClusterDependentMultiscalePublic
