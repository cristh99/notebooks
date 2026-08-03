namespace LogicPowerKnowledgeActionLoop

inductive KnowledgeId where
  | mk (value : String)
  deriving DecidableEq, Repr

inductive ActionId where
  | mk (value : String)
  deriving DecidableEq, Repr

inductive ItemRef where
  | knowledge (id : KnowledgeId)
  | action (id : ActionId)
  deriving DecidableEq, Repr

inductive ActionState where
  | asap
  | atADate
  | doing
  | done
  | somedayMaybe
  | trash
  deriving DecidableEq, Repr

inductive Verdict where
  | kill
  | change
  | move
  | merge
  | create
  | noChange
  deriving DecidableEq, Repr

def executable : ActionState → Bool
  | .asap => true
  | .atADate => true
  | .doing => true
  | .done => false
  | .somedayMaybe => false
  | .trash => false

def consequenceTarget : Verdict → Option ActionState
  | .kill => some .trash
  | .change => some .asap
  | .move => some .asap
  | .merge => some .somedayMaybe
  | .create => some .somedayMaybe
  | .noChange => none

def doingGate (authorized preflight mandate : Bool) : Bool :=
  authorized && preflight && mandate

def doneGate (verifiedEvidence : Bool) : Bool := verifiedEvidence

def integrationGate
    (done verifiedEvidence generalizable exactStatement : Bool) : Bool :=
  done && verifiedEvidence && generalizable && exactStatement

def mandateGate
    (state : ActionState) (authorized due : Bool) : Bool :=
  authorized &&
    match state with
    | .asap => true
    | .atADate => due
    | .doing => true
    | _ => false

def microStepAuthority (authorized : Bool) : Bool := authorized

def integratedStatement (verifiedStatement : String) : String := verifiedStatement

theorem knowledge_and_action_roles_are_disjoint
    (knowledgeId : KnowledgeId) (actionId : ActionId) :
    ItemRef.knowledge knowledgeId ≠ ItemRef.action actionId := by
  intro h
  cases h

theorem someday_maybe_is_not_executable :
    executable .somedayMaybe = false := by
  rfl

theorem trash_is_not_executable :
    executable .trash = false := by
  rfl

theorem no_change_creates_no_action :
    consequenceTarget .noChange = none := by
  rfl

theorem create_starts_without_commitment :
    consequenceTarget .create = some .somedayMaybe := by
  rfl

theorem knowledge_cannot_directly_claim_doing (verdict : Verdict) :
    consequenceTarget verdict ≠ some .doing := by
  cases verdict <;> decide

theorem doing_requires_authority
    (authorized preflight mandate : Bool)
    (h : doingGate authorized preflight mandate = true) :
    authorized = true := by
  cases authorized <;> cases preflight <;> cases mandate <;> decide

theorem doing_requires_preflight
    (authorized preflight mandate : Bool)
    (h : doingGate authorized preflight mandate = true) :
    preflight = true := by
  cases authorized <;> cases preflight <;> cases mandate <;> decide

theorem doing_requires_solver_mandate
    (authorized preflight mandate : Bool)
    (h : doingGate authorized preflight mandate = true) :
    mandate = true := by
  cases authorized <;> cases preflight <;> cases mandate <;> decide

theorem done_requires_verified_evidence
    (verifiedEvidence : Bool)
    (h : doneGate verifiedEvidence = true) :
    verifiedEvidence = true := by
  cases verifiedEvidence <;> decide

theorem integration_requires_verified_evidence
    (done verifiedEvidence generalizable exactStatement : Bool)
    (h : integrationGate done verifiedEvidence generalizable exactStatement = true) :
    verifiedEvidence = true := by
  cases done <;> cases verifiedEvidence <;>
    cases generalizable <;> cases exactStatement <;> decide

theorem integration_requires_generalizable_result
    (done verifiedEvidence generalizable exactStatement : Bool)
    (h : integrationGate done verifiedEvidence generalizable exactStatement = true) :
    generalizable = true := by
  cases done <;> cases verifiedEvidence <;>
    cases generalizable <;> cases exactStatement <;> decide

theorem solver_mandate_requires_authorized_executable_work
    (state : ActionState) (authorized due : Bool)
    (h : mandateGate state authorized due = true) :
    authorized = true ∧ executable state = true := by
  cases state <;> cases authorized <;> cases due <;> decide

theorem microcycle_preserves_macro_authority (authorized : Bool) :
    microStepAuthority authorized = authorized := by
  rfl

theorem integration_preserves_verified_statement (statement : String) :
    integratedStatement statement = statement := by
  rfl

#print axioms knowledge_and_action_roles_are_disjoint
#print axioms someday_maybe_is_not_executable
#print axioms trash_is_not_executable
#print axioms no_change_creates_no_action
#print axioms create_starts_without_commitment
#print axioms knowledge_cannot_directly_claim_doing
#print axioms doing_requires_authority
#print axioms doing_requires_preflight
#print axioms doing_requires_solver_mandate
#print axioms done_requires_verified_evidence
#print axioms integration_requires_verified_evidence
#print axioms integration_requires_generalizable_result
#print axioms solver_mandate_requires_authorized_executable_work
#print axioms microcycle_preserves_macro_authority
#print axioms integration_preserves_verified_statement

end LogicPowerKnowledgeActionLoop
