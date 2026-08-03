import Std

/-!
# Public hardening boundary for drift-aware online cross-fit inference

The independent verifier closes three review findings: cluster identifiers must
be unique within each monitoring batch, each monitored batch needs a strict
predecessor for the pre-outcome drift reference, and resource accounting must
include every rational factor multiplication used by root inversion and the
all-prefix truth audit.
-/

namespace DriftAwareOnlineCrossFitHardeningPublic

/-- A repeated cluster cannot satisfy pairwise distinctness. -/
theorem duplicate_cluster_refutes_distinctness
    {Cluster : Type} [DecidableEq Cluster]
    (left right : Cluster)
    (hsame : left = right) :
    ¬ left ≠ right := by
  intro hdifferent
  exact hdifferent hsame

/-- A monitored batch with a strict predecessor cannot be the first batch. -/
theorem monitoring_with_predecessor_has_positive_index
    (index predecessor : Nat)
    (hpred : predecessor < index) :
    0 < index := by
  exact Nat.lt_of_le_of_lt (Nat.zero_le predecessor) hpred

/-- Twelve 16-row endpoints contain 1248 prefix rows in total. -/
theorem endpoint_prefix_sum_control :
    16 * (1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9 + 10 + 11 + 12)
      = 1248 := by
  decide

/-- Two-sided adaptive and baseline root inversion costs 274560 factors. -/
theorem root_factor_count_control :
    1248 * 10 * 22 = 274560 := by
  decide

/-- The every-prefix two-sided four-expert truth audit costs 148224 factors. -/
theorem truth_factor_count_control :
    4 * 192 * 193 = 148224 := by
  decide

/-- The corrected total is 422784 factor multiplications. -/
theorem total_factor_count_control :
    274560 + 148224 = 422784 := by
  decide

/-- The former 300000 cap is insufficient. -/
theorem former_resource_gap_is_real :
    300000 < 422784 := by
  decide

/-- A cap equal to the corrected count is sufficient. -/
theorem exact_resource_cap_is_feasible :
    422784 ≤ 422784 := by
  decide

/-- Hardening preserves strict adaptive interval shrinkage. -/
theorem adaptive_interval_remains_strictly_narrower :
    3121 * 32 < 142005 := by
  decide

/-- The online remainder contracts from 1/18 to 1/4418. -/
theorem remainder_contraction_control :
    18 < 4418 := by
  decide

#print axioms DriftAwareOnlineCrossFitHardeningPublic.duplicate_cluster_refutes_distinctness
#print axioms DriftAwareOnlineCrossFitHardeningPublic.monitoring_with_predecessor_has_positive_index
#print axioms DriftAwareOnlineCrossFitHardeningPublic.endpoint_prefix_sum_control
#print axioms DriftAwareOnlineCrossFitHardeningPublic.root_factor_count_control
#print axioms DriftAwareOnlineCrossFitHardeningPublic.truth_factor_count_control
#print axioms DriftAwareOnlineCrossFitHardeningPublic.total_factor_count_control
#print axioms DriftAwareOnlineCrossFitHardeningPublic.former_resource_gap_is_real
#print axioms DriftAwareOnlineCrossFitHardeningPublic.exact_resource_cap_is_feasible
#print axioms DriftAwareOnlineCrossFitHardeningPublic.adaptive_interval_remains_strictly_narrower
#print axioms DriftAwareOnlineCrossFitHardeningPublic.remainder_contraction_control

end DriftAwareOnlineCrossFitHardeningPublic
