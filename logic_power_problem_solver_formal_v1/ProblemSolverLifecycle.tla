---- MODULE ProblemSolverLifecycle ----
EXTENDS TLC

CONSTANT Scenario
VARIABLES phase, selected, status, evidence

vars == <<phase, selected, status, evidence>>

Scenarios == {
  "Exact",
  "Search",
  "LearnedReady",
  "LearnedMissing",
  "Unsafe",
  "Underspecified",
  "Impossible",
  "NoBudget"
}
Phases == {"Parsed", "Routed", "Executing", "Terminal"}
Solvers == {"None", "planner", "mcts", "muzero"}
Statuses == {
  "NONE",
  "SOLVED",
  "IMPOSSIBLE",
  "BLOCKED",
  "UNDERSPECIFIED",
  "BUDGET_EXHAUSTED",
  "UNSAFE"
}

Init ==
  /\ phase = "Parsed"
  /\ selected = "None"
  /\ status = "NONE"
  /\ evidence = FALSE

RouteTerminal ==
  /\ phase = "Parsed"
  /\ \/ /\ Scenario = "LearnedMissing"
         /\ status' = "BLOCKED"
     \/ /\ Scenario = "Unsafe"
         /\ status' = "UNSAFE"
     \/ /\ Scenario = "Underspecified"
         /\ status' = "UNDERSPECIFIED"
     \/ /\ Scenario = "Impossible"
         /\ status' = "IMPOSSIBLE"
     \/ /\ Scenario = "NoBudget"
         /\ status' = "BUDGET_EXHAUSTED"
  /\ phase' = "Terminal"
  /\ selected' = "None"
  /\ evidence' = FALSE

RouteSolver ==
  /\ phase = "Parsed"
  /\ Scenario \in {"Exact", "Search", "LearnedReady"}
  /\ phase' = "Routed"
  /\ selected' =
       CASE Scenario = "Exact" -> "planner"
         [] Scenario = "Search" -> "mcts"
         [] OTHER -> "muzero"
  /\ status' = "NONE"
  /\ evidence' = FALSE

Route == RouteTerminal \/ RouteSolver

Execute ==
  /\ phase = "Routed"
  /\ phase' = "Executing"
  /\ UNCHANGED <<selected, status, evidence>>

Finish ==
  /\ phase = "Executing"
  /\ phase' = "Terminal"
  /\ status' = "SOLVED"
  /\ evidence' = TRUE
  /\ UNCHANGED selected

Next == Route \/ Execute \/ Finish

Spec ==
  /\ Init
  /\ [][Next]_vars
  /\ WF_vars(Route)
  /\ WF_vars(Execute)
  /\ WF_vars(Finish)

TypeOK ==
  /\ Scenario \in Scenarios
  /\ phase \in Phases
  /\ selected \in Solvers
  /\ status \in Statuses
  /\ evidence \in BOOLEAN

TerminalStatusIff ==
  (phase = "Terminal") <=> (status # "NONE")

SolvedHasEvidence ==
  (status = "SOLVED") => evidence

BlockedHasNoSolver ==
  (status = "BLOCKED") => (selected = "None")

MuZeroNeedsPrerequisites ==
  (selected = "muzero") => (Scenario = "LearnedReady")

UnsafeNeverExecutes ==
  (Scenario = "Unsafe") =>
    (phase \notin {"Routed", "Executing"} /\ status # "SOLVED")

TerminalLegitimate ==
  (phase = "Terminal") =>
    status \in {
      "SOLVED",
      "IMPOSSIBLE",
      "BLOCKED",
      "UNDERSPECIFIED",
      "BUDGET_EXHAUSTED",
      "UNSAFE"
    }

Termination == <> (phase = "Terminal")

====
