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


theorem bool_and_left_true {a b : Bool}
    (h : a && b = true) : a = true := by
  cases a with
  | false => cases h
  | true => rfl


theorem bool_and_right_true {a b : Bool}
    (h : a && b = true) : b = true := by
  cases a with
  | false => cases h
  | true =>
      change b = true at h
      exact h


theorem planning_rejects_logic_exact
    (problem : Problem) (h : problem.planning = true) :
    eligible problem .logicExact = false := by
  change (!problem.planning && !problem.game) = false
  rw [h]
  rfl


theorem planning_rejects_one_shot_bayes
    (problem : Problem) (h : problem.planning = true) :
    eligible problem .bayes = false := by
  change
    ((!problem.planning && !problem.game) &&
      problem.staticHorizon) = false
  rw [h]
  rfl


theorem monte_carlo_is_support_only :
    primaryAllowed .monteCarlo ≠ true := by
  change false ≠ true
  intro h
  cases h


theorem dynamic_programming_requires_exact_scope
    (problem : Problem)
    (h : eligible problem .dynamicProgramming = true) :
    problem.planning = true ∧
      problem.singleAgent = true ∧
      problem.knownModel = true := by
  change
    ((problem.planning && problem.singleAgent) &&
      problem.knownModel) = true at h
  have known := bool_and_right_true h
  have pair := bool_and_left_true h
  have single := bool_and_right_true pair
  have planning := bool_and_left_true pair
  exact ⟨planning, ⟨single, known⟩⟩


theorem mcts_requires_declared_simulator_scope
    (problem : Problem)
    (h : eligible problem .mcts = true) :
    problem.planning = true ∧
      problem.singleAgent = true ∧
      problem.simulator = true ∧
      problem.rolloutBudget = true ∧
      problem.depthBudget = true := by
  change
    ((((problem.planning && problem.singleAgent) &&
      problem.simulator) && problem.rolloutBudget) &&
      problem.depthBudget) = true at h
  have depth := bool_and_right_true h
  have four := bool_and_left_true h
  have rollout := bool_and_right_true four
  have three := bool_and_left_true four
  have simulator := bool_and_right_true three
  have two := bool_and_left_true three
  have single := bool_and_right_true two
  have planning := bool_and_left_true two
  exact
    ⟨planning, ⟨single, ⟨simulator, ⟨rollout, depth⟩⟩⟩⟩


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
  change
    (((((((problem.planning && problem.singleAgent) &&
      problem.learnableModel) && problem.interactionData) &&
      problem.rewardSignal) && problem.neuralTraining) &&
      problem.rolloutBudget) && problem.depthBudget) = true at h
  have depth := bool_and_right_true h
  have seven := bool_and_left_true h
  have rollout := bool_and_right_true seven
  have six := bool_and_left_true seven
  have neural := bool_and_right_true six
  have five := bool_and_left_true six
  have reward := bool_and_right_true five
  have four := bool_and_left_true five
  have interaction := bool_and_right_true four
  have three := bool_and_left_true four
  have learnable := bool_and_right_true three
  have two := bool_and_left_true three
  have single := bool_and_right_true two
  have planning := bool_and_left_true two
  exact
    ⟨planning,
      ⟨single,
        ⟨learnable,
          ⟨interaction,
            ⟨reward,
              ⟨neural,
                ⟨rollout, depth⟩⟩⟩⟩⟩⟩⟩


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
