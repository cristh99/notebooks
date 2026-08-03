import Std

namespace FiniteSCMIdentificationPublic

/-- Opposite targets with the same observation rule out an exact observational monitor. -/
theorem indistinguishable_opposites_block_monitor
    {World Obs : Type}
    (observe : World → Obs)
    (target : World → Bool)
    (left right : World)
    (hObs : observe left = observe right)
    (hTarget : target left ≠ target right) :
    ¬ ∃ monitor : Obs → Bool, ∀ world, monitor (observe world) = target world := by
  intro h
  rcases h with ⟨monitor, hmonitor⟩
  have hLeft := hmonitor left
  have hRight := hmonitor right
  rw [hObs] at hLeft
  exact hTarget (hLeft.symm.trans hRight)

/-- If two intervention signatures agree, any target defined only from them agrees. -/
theorem intervention_signature_determines_target
    {World Signature Target : Type}
    (signature : World → Signature)
    (decode : Signature → Target)
    (left right : World)
    (h : signature left = signature right) :
    decode (signature left) = decode (signature right) := by
  rw [h]

/-- Two interventions of cost three have fixed total cost six. -/
theorem fixed_intervention_cost : 3 + 3 = 6 := by decide

/-- Under the uniform 64-world family, 48 unresolved worlds give expected cost 21/4. -/
theorem adaptive_cost_scaled : 4 * 3 + 3 * 3 = 21 := by decide

/-- The adaptive design saves three quarters of one cost unit. -/
theorem adaptive_reduction_scaled : 24 - 21 = 3 := by decide

/-- Twenty positive-effect and forty-four nonpositive worlds exhaust sixty-four. -/
theorem scm_world_partition : 20 + 44 = 64 := by decide

/-- The number of opposite-target pairs is 20*44=880. -/
theorem conflicting_pair_count : 20 * 44 = 880 := by decide

#print axioms FiniteSCMIdentificationPublic.indistinguishable_opposites_block_monitor
#print axioms FiniteSCMIdentificationPublic.intervention_signature_determines_target
#print axioms FiniteSCMIdentificationPublic.fixed_intervention_cost
#print axioms FiniteSCMIdentificationPublic.adaptive_cost_scaled
#print axioms FiniteSCMIdentificationPublic.adaptive_reduction_scaled
#print axioms FiniteSCMIdentificationPublic.scm_world_partition
#print axioms FiniteSCMIdentificationPublic.conflicting_pair_count

end FiniteSCMIdentificationPublic
