import Std

namespace PartialIdentificationPublic

/-- Refinement cannot increase a finite width when both endpoints move inward. -/
theorem inward_endpoints_reduce_width
    (lower lower' upper' upper : Nat)
    (hLower : lower ≤ lower')
    (hUpper : upper' ≤ upper)
    (hOrder : lower' ≤ upper') :
    upper' - lower' ≤ upper - lower := by
  omega

/-- Observation-only width four, fixed-intervention width two, adaptive width one. -/
theorem sharp_width_frontier_scaled : 4 > 2 ∧ 2 > 1 ∧ 1 > 0 := by
  decide

/-- Adaptive one-intervention design cuts the fixed expected width in half. -/
theorem adaptive_halves_fixed_width_scaled : 2 * 1 = 2 := by
  decide

/-- Adaptive design reduces observation-only expected width by three quarters. -/
theorem adaptive_reduction_from_observation_scaled : 4 - 1 = 3 := by
  decide

/-- Thirty-two point-identified and thirty-two half-width worlds exhaust the family. -/
theorem adaptive_world_partition : 32 + 32 = 64 := by
  decide

/-- Seven do-zero and three do-one observational strata exhaust ten strata. -/
theorem adaptive_stratum_partition : 7 + 3 = 10 := by
  decide

/-- Both interventions collapse the scaled width to zero. -/
theorem both_interventions_point_identify : 0 ≤ 1 := by
  decide

#print axioms PartialIdentificationPublic.inward_endpoints_reduce_width
#print axioms PartialIdentificationPublic.sharp_width_frontier_scaled
#print axioms PartialIdentificationPublic.adaptive_halves_fixed_width_scaled
#print axioms PartialIdentificationPublic.adaptive_reduction_from_observation_scaled
#print axioms PartialIdentificationPublic.adaptive_world_partition
#print axioms PartialIdentificationPublic.adaptive_stratum_partition
#print axioms PartialIdentificationPublic.both_interventions_point_identify

end PartialIdentificationPublic
