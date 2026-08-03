---- MODULE KnowledgeActionLoop ----
EXTENDS TLC

CONSTANT Scenario
VARIABLES phase, knowledge, actionState, consequence, authorized,
          preflight, live, evidence, generalizable, integrated,
          mandate, verdict, status

vars == <<phase, knowledge, actionState, consequence, authorized,
          preflight, live, evidence, generalizable, integrated,
          mandate, verdict, status>>

Scenarios == {
  "NoChange", "MoveExisting", "LocalOnly", "Generalizable",
  "FailedPreflight", "FutureDate", "Kill",
  "CreateAfterSearch", "KnowledgeExecute"
}
Phases == {
  "Captured", "Classified", "Bridged", "Mandated",
  "Executing", "Verified", "Integrated", "Terminal"
}
ActionStates == {
  "NONE", "SOMEDAY_MAYBE", "ASAP", "AT_A_DATE",
  "DOING", "DONE", "TRASH"
}
Verdicts == {
  "NONE", "MATAR", "CAMBIAR", "MOVER",
  "FUSIONAR", "CREAR", "SIN_CAMBIO"
}
Statuses == {"NONE", "PASS", "BLOCKED", "UNSAFE"}

Init ==
  /\ phase = "Captured"
  /\ knowledge = FALSE
  /\ actionState = "NONE"
  /\ consequence = FALSE
  /\ authorized = FALSE
  /\ preflight = FALSE
  /\ live = FALSE
  /\ evidence = FALSE
  /\ generalizable = FALSE
  /\ integrated = FALSE
  /\ mandate = FALSE
  /\ verdict = "NONE"
  /\ status = "NONE"

Classify ==
  /\ phase = "Captured"
  /\ knowledge' =
       Scenario \in {
         "NoChange", "MoveExisting", "Kill",
         "CreateAfterSearch", "KnowledgeExecute"
       }
  /\ actionState' =
       CASE Scenario \in {"NoChange", "KnowledgeExecute", "CreateAfterSearch"}
              -> "NONE"
         [] Scenario \in {"MoveExisting", "Kill"} -> "SOMEDAY_MAYBE"
         [] Scenario = "FutureDate" -> "AT_A_DATE"
         [] OTHER -> "ASAP"
  /\ authorized' =
       Scenario \in {
         "LocalOnly", "Generalizable",
         "FailedPreflight", "FutureDate"
       }
  /\ preflight' = Scenario \in {"LocalOnly", "Generalizable"}
  /\ generalizable' = Scenario \in {"MoveExisting", "Generalizable"}
  /\ phase' =
       CASE Scenario \in {
              "NoChange", "MoveExisting", "Kill",
              "CreateAfterSearch", "KnowledgeExecute"
            } -> "Classified"
         [] OTHER -> "Bridged"
  /\ UNCHANGED <<consequence, live, evidence, integrated,
                 mandate, verdict, status>>

BridgeNoChange ==
  /\ phase = "Classified"
  /\ Scenario = "NoChange"
  /\ phase' = "Terminal"
  /\ consequence' = TRUE
  /\ verdict' = "SIN_CAMBIO"
  /\ status' = "PASS"
  /\ UNCHANGED <<knowledge, actionState, authorized, preflight,
                 live, evidence, generalizable, integrated, mandate>>

BridgeMove ==
  /\ phase = "Classified"
  /\ Scenario = "MoveExisting"
  /\ phase' = "Bridged"
  /\ actionState' = "ASAP"
  /\ consequence' = TRUE
  /\ authorized' = TRUE
  /\ preflight' = TRUE
  /\ verdict' = "MOVER"
  /\ UNCHANGED <<knowledge, live, evidence, generalizable,
                 integrated, mandate, status>>

BridgeKill ==
  /\ phase = "Classified"
  /\ Scenario = "Kill"
  /\ phase' = "Terminal"
  /\ actionState' = "TRASH"
  /\ consequence' = TRUE
  /\ verdict' = "MATAR"
  /\ status' = "PASS"
  /\ UNCHANGED <<knowledge, authorized, preflight, live,
                 evidence, generalizable, integrated, mandate>>

BridgeCreate ==
  /\ phase = "Classified"
  /\ Scenario = "CreateAfterSearch"
  /\ phase' = "Terminal"
  /\ actionState' = "SOMEDAY_MAYBE"
  /\ consequence' = TRUE
  /\ verdict' = "CREAR"
  /\ status' = "PASS"
  /\ UNCHANGED <<knowledge, authorized, preflight, live,
                 evidence, generalizable, integrated, mandate>>

RejectKnowledgeExecution ==
  /\ phase = "Classified"
  /\ Scenario = "KnowledgeExecute"
  /\ phase' = "Terminal"
  /\ verdict' = "SIN_CAMBIO"
  /\ status' = "UNSAFE"
  /\ UNCHANGED <<knowledge, actionState, consequence, authorized,
                 preflight, live, evidence, generalizable,
                 integrated, mandate>>

IssueMandate ==
  /\ phase = "Bridged"
  /\ Scenario \in {
       "MoveExisting", "LocalOnly",
       "Generalizable", "FailedPreflight"
     }
  /\ actionState = "ASAP"
  /\ authorized
  /\ phase' = "Mandated"
  /\ mandate' = TRUE
  /\ UNCHANGED <<knowledge, actionState, consequence, authorized,
                 preflight, live, evidence, generalizable,
                 integrated, verdict, status>>

WaitFutureDate ==
  /\ phase = "Bridged"
  /\ Scenario = "FutureDate"
  /\ actionState = "AT_A_DATE"
  /\ phase' = "Terminal"
  /\ verdict' = "SIN_CAMBIO"
  /\ status' = "BLOCKED"
  /\ UNCHANGED <<knowledge, actionState, consequence, authorized,
                 preflight, live, evidence, generalizable,
                 integrated, mandate>>

RejectPreflight ==
  /\ phase = "Mandated"
  /\ Scenario = "FailedPreflight"
  /\ ~preflight
  /\ phase' = "Terminal"
  /\ verdict' = "SIN_CAMBIO"
  /\ status' = "BLOCKED"
  /\ UNCHANGED <<knowledge, actionState, consequence, authorized,
                 preflight, live, evidence, generalizable,
                 integrated, mandate>>

Start ==
  /\ phase = "Mandated"
  /\ preflight
  /\ mandate
  /\ authorized
  /\ phase' = "Executing"
  /\ actionState' = "DOING"
  /\ live' = TRUE
  /\ UNCHANGED <<knowledge, consequence, authorized, preflight,
                 evidence, generalizable, integrated, mandate,
                 verdict, status>>

ProduceEvidence ==
  /\ phase = "Executing"
  /\ actionState = "DOING"
  /\ live
  /\ phase' = "Verified"
  /\ actionState' = "DONE"
  /\ live' = FALSE
  /\ evidence' = TRUE
  /\ UNCHANGED <<knowledge, consequence, authorized, preflight,
                 generalizable, integrated, mandate, verdict, status>>

Integrate ==
  /\ phase = "Verified"
  /\ actionState = "DONE"
  /\ evidence
  /\ generalizable
  /\ phase' = "Integrated"
  /\ integrated' = TRUE
  /\ UNCHANGED <<knowledge, actionState, consequence, authorized,
                 preflight, live, evidence, generalizable,
                 mandate, verdict, status>>

CloseIntegrated ==
  /\ phase = "Integrated"
  /\ integrated
  /\ phase' = "Terminal"
  /\ verdict' = "SIN_CAMBIO"
  /\ status' = "PASS"
  /\ UNCHANGED <<knowledge, actionState, consequence, authorized,
                 preflight, live, evidence, generalizable,
                 integrated, mandate>>

CloseLocalOnly ==
  /\ phase = "Verified"
  /\ actionState = "DONE"
  /\ evidence
  /\ ~generalizable
  /\ phase' = "Terminal"
  /\ verdict' = "SIN_CAMBIO"
  /\ status' = "PASS"
  /\ UNCHANGED <<knowledge, actionState, consequence, authorized,
                 preflight, live, evidence, generalizable,
                 integrated, mandate>>

TerminalStutter ==
  /\ phase = "Terminal"
  /\ UNCHANGED vars

Next ==
  Classify \/ BridgeNoChange \/ BridgeMove \/ BridgeKill \/ BridgeCreate
  \/ RejectKnowledgeExecution \/ IssueMandate \/ WaitFutureDate
  \/ RejectPreflight \/ Start \/ ProduceEvidence \/ Integrate
  \/ CloseIntegrated \/ CloseLocalOnly \/ TerminalStutter

Spec ==
  /\ Init
  /\ [][Next]_vars
  /\ WF_vars(Next)

TypeOK ==
  /\ Scenario \in Scenarios
  /\ phase \in Phases
  /\ knowledge \in BOOLEAN
  /\ actionState \in ActionStates
  /\ consequence \in BOOLEAN
  /\ authorized \in BOOLEAN
  /\ preflight \in BOOLEAN
  /\ live \in BOOLEAN
  /\ evidence \in BOOLEAN
  /\ generalizable \in BOOLEAN
  /\ integrated \in BOOLEAN
  /\ mandate \in BOOLEAN
  /\ verdict \in Verdicts
  /\ status \in Statuses

TerminalStatusIff == (phase = "Terminal") <=> (status # "NONE")
DoingRequiresGates ==
  (actionState = "DOING") => (authorized /\ preflight /\ live /\ mandate)
DoneRequiresEvidence == (actionState = "DONE") => evidence
IntegrationRequiresVerifiedGeneralizableResult ==
  integrated => (evidence /\ generalizable /\ actionState = "DONE")
MandateRequiresAuthorizedExecutableWork ==
  mandate => (authorized /\ actionState \in {"ASAP", "DOING", "DONE"})
SomedayMaybeIsNotExecutable ==
  (actionState = "SOMEDAY_MAYBE") => (~live /\ ~mandate)
NoChangeCreatesNoAction ==
  (Scenario = "NoChange") => (actionState = "NONE")
KnowledgeCannotExecute ==
  (Scenario = "KnowledgeExecute") => (actionState # "DOING" /\ status # "PASS")
CreateStartsWithoutCommitment ==
  (verdict = "CREAR") => (actionState = "SOMEDAY_MAYBE" /\ ~authorized /\ ~live)
KillEndsInTrash == (verdict = "MATAR") => (actionState = "TRASH")
PassHasFeedback == (status = "PASS") => (verdict # "NONE")
KnowledgeToActionRequiresConsequence ==
  (Scenario = "MoveExisting" /\ actionState \in {"ASAP", "DOING", "DONE"}) => consequence
ActionToKnowledgeRequiresEvidence == integrated => evidence
FutureDateCannotIssueMandateEarly == (Scenario = "FutureDate") => ~mandate
Termination == <> (phase = "Terminal")

====
