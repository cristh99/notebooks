namespace ProblemSolverBoundary

inductive Solver where
  | logicExact
  | bayes
  | monteCarlo
  | dynamicProgramming
  | mcts
  | muzero
  deriving DecidableEq, Repr

structure Problem where
  planning : Bool
  game : Bool
  staticHorizon : Bool
  singleAgent : Bool
  knownModel : Bool
  simulator : Bool
  learnableModel : Bool
  interactionData : Bool
  rewardSignal : Bool
  neuralTraining : Bool
  rolloutBudget : Bool
  depthBudget : Bool


def eligible (problem : Problem) : Solver → Bool
  | .logicExact => !problem.planning && !problem.game
  | .bayes =>
      !problem.planning && !problem.game && problem.staticHorizon
  | .monteCarlo => problem.rolloutBudget
  | .dynamicProgramming =>
      problem.planning && problem.singleAgent && problem.knownModel
  | .mcts =>
      problem.planning && problem.singleAgent && problem.simulator &&
        problem.rolloutBudget && problem.depthBudget
  | .muzero =>
      problem.planning && problem.singleAgent && problem.learnableModel &&
        problem.interactionData && problem.rewardSignal &&
        problem.neuralTraining && problem.rolloutBudget &&
        problem.depthBudget


def primaryAllowed : Solver → Bool
  | .monteCarlo => false
  | _ => true


theorem planning_rejects_logic_exact
    (problem : Problem) (h : problem.planning = true) :
    eligible problem .logicExact = false := by
  simp [eligible, h]


theorem planning_rejects_one_shot_bayes
    (problem : Problem) (h : problem.planning = true) :
    eligible problem .bayes = false := by
  simp [eligible, h]


theorem monte_carlo_is_support_only :
    primaryAllowed .monteCarlo = false := by
  rfl


theorem dynamic_programming_requires_exact_scope
    (problem : Problem)
    (h : eligible problem .dynamicProgramming = true) :
    problem.planning = true ∧
      problem.singleAgent = true ∧
      problem.knownModel = true := by
  simpa [eligible, Bool.and_eq_true] using h


theorem mcts_requires_declared_simulator_scope
    (problem : Problem)
    (h : eligible problem .mcts = true) :
    problem.planning = true ∧
      problem.singleAgent = true ∧
      problem.simulator = true ∧
      problem.rolloutBudget = true ∧
      problem.depthBudget = true := by
  simpa [eligible, Bool.and_eq_true] using h


theorem muzero_requires_all_prerequisites
    (problem : Problem)
    (h : eligible problem .muzero = true) :
    problem.planning = true ∧
      problem.singleAgent = true ∧
      problem.learnableModel = true ∧
      problem.interactionData = true ∧
      problem.rewardSignal = true ∧
      problem.neuralTraining = true ∧
      problem.rolloutBudget = true ∧
      problem.depthBudget = true := by
  simpa [eligible, Bool.and_eq_true] using h


inductive RootAction where
  | safe
  | explore
  deriving DecidableEq, Repr


def rootValue : RootAction → Int
  | .safe => 4
  | .explore => 10


theorem explore_is_optimal (action : RootAction) :
    rootValue action ≤ rootValue .explore := by
  cases action <;> decide


#print axioms planning_rejects_logic_exact
#print axioms planning_rejects_one_shot_bayes
#print axioms monte_carlo_is_support_only
#print axioms dynamic_programming_requires_exact_scope
#print axioms mcts_requires_declared_simulator_scope
#print axioms muzero_requires_all_prerequisites
#print axioms explore_is_optimal

end ProblemSolverBoundary
