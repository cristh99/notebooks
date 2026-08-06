From LF Require Import Basics Induction Lists Poly Tactics Logic IndProp Maps Imp.

Module UniversitySoftwareFoundationsRuntime.

(** This file checks representative mechanisms from the Logical Foundations
    curriculum in the real Rocq kernel.  It is intentionally scoped and does
    not claim completion of every exercise in the official volume. *)

Theorem plus_zero_right_runtime : forall n : nat,
  n + 0 = n.
Proof.
  induction n as [| n IH].
  - reflexivity.
  - simpl. rewrite IH. reflexivity.
Qed.

Fixpoint runtime_rev {X : Type} (xs : list X) : list X :=
  match xs with
  | nil => nil
  | x :: rest => runtime_rev rest ++ [x]
  end.

Lemma runtime_rev_append : forall (X : Type) (xs ys : list X),
  runtime_rev (xs ++ ys) = runtime_rev ys ++ runtime_rev xs.
Proof.
  intros X xs ys.
  induction xs as [| x xs IH].
  - simpl. rewrite app_nil_r. reflexivity.
  - simpl. rewrite IH. rewrite app_assoc. reflexivity.
Qed.

Theorem runtime_rev_involutive : forall (X : Type) (xs : list X),
  runtime_rev (runtime_rev xs) = xs.
Proof.
  intros X xs.
  induction xs as [| x xs IH].
  - reflexivity.
  - simpl. rewrite runtime_rev_append. simpl. rewrite IH. reflexivity.
Qed.

Inductive runtime_even : nat -> Prop :=
  | runtime_even_O : runtime_even 0
  | runtime_even_SS : forall n, runtime_even n -> runtime_even (S (S n)).

Theorem runtime_even_double : forall n,
  runtime_even (n + n).
Proof.
  induction n as [| n IH].
  - simpl. apply runtime_even_O.
  - simpl. rewrite <- plus_n_Sm. apply runtime_even_SS. exact IH.
Qed.

Inductive runtime_expr : Type :=
  | RNum (n : nat)
  | RPlus (lhs rhs : runtime_expr).

Fixpoint runtime_eval (e : runtime_expr) : nat :=
  match e with
  | RNum n => n
  | RPlus lhs rhs => runtime_eval lhs + runtime_eval rhs
  end.

Fixpoint runtime_fold_constants (e : runtime_expr) : runtime_expr :=
  match e with
  | RNum n => RNum n
  | RPlus lhs rhs =>
      match runtime_fold_constants lhs, runtime_fold_constants rhs with
      | RNum n, RNum m => RNum (n + m)
      | lhs', rhs' => RPlus lhs' rhs'
      end
  end.

Theorem runtime_fold_constants_sound : forall e,
  runtime_eval (runtime_fold_constants e) = runtime_eval e.
Proof.
  induction e as [n | lhs IHlhs rhs IHrhs].
  - reflexivity.
  - simpl.
    remember (runtime_fold_constants lhs) as lhs' eqn:Hlhs.
    remember (runtime_fold_constants rhs) as rhs' eqn:Hrhs.
    destruct lhs'; destruct rhs'; simpl in *; rewrite <- IHlhs, <- IHrhs;
      rewrite Hlhs, Hrhs; reflexivity.
Qed.

Definition runtime_assertion := nat -> Prop.
Definition runtime_relation := nat -> nat -> Prop.

Definition runtime_hoare
    (P : runtime_assertion)
    (step : runtime_relation)
    (Q : runtime_assertion) : Prop :=
  forall before after, P before -> step before after -> Q after.

Definition runtime_increment (before after : nat) : Prop :=
  after = S before.

Theorem runtime_increment_rule : forall bound,
  runtime_hoare
    (fun before => before = bound)
    runtime_increment
    (fun after => after = S bound).
Proof.
  intros bound before after Hbefore Hstep.
  unfold runtime_increment in Hstep.
  subst before. exact Hstep.
Qed.

Theorem runtime_existential_transport : forall (X : Type) (P Q : X -> Prop),
  (forall x, P x -> Q x) ->
  (exists x, P x) ->
  exists x, Q x.
Proof.
  intros X P Q Himp [x HP].
  exists x. apply Himp. exact HP.
Qed.

Print Assumptions plus_zero_right_runtime.
Print Assumptions runtime_rev_append.
Print Assumptions runtime_rev_involutive.
Print Assumptions runtime_even_double.
Print Assumptions runtime_fold_constants_sound.
Print Assumptions runtime_increment_rule.
Print Assumptions runtime_existential_transport.

End UniversitySoftwareFoundationsRuntime.
