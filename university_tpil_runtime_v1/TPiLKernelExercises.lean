import Std

namespace UniversityTPiLRuntime

/-!
A small, scoped runtime capsule covering representative mechanisms from
Theorem Proving in Lean 4. This is not a claim that the full book is complete.
-/

theorem identity {P : Prop} (h : P) : P := h

theorem implication_transitivity {P Q R : Prop} :
    (P → Q) → (Q → R) → P → R :=
  fun hpq hqr hp => hqr (hpq hp)

theorem and_commutative {P Q : Prop} : P ∧ Q → Q ∧ P := by
  intro h
  exact ⟨h.right, h.left⟩

theorem or_commutative {P Q : Prop} : P ∨ Q → Q ∨ P := by
  intro h
  cases h with
  | inl hp => exact Or.inr hp
  | inr hq => exact Or.inl hq

theorem exists_swap {α : Type} {P Q : α → Prop} :
    (∃ x, P x ∧ Q x) → ∃ x, Q x ∧ P x :=
  fun ⟨x, hp, hq⟩ => ⟨x, hq, hp⟩

theorem equality_symmetric {α : Type} {a b : α} (h : a = b) : b = a :=
  Eq.symm h

structure Point where
  x : Nat
  y : Nat
  deriving DecidableEq, Repr

def Point.swap (p : Point) : Point := ⟨p.y, p.x⟩

theorem Point.swap_swap (p : Point) : p.swap.swap = p := by
  cases p
  rfl

inductive Vec (α : Type u) : Nat → Type u where
  | nil : Vec α 0
  | cons : α → Vec α n → Vec α (n + 1)

def Vec.head {α : Type u} {n : Nat} : Vec α (n + 1) → α
  | .cons x _ => x

theorem Vec.head_cons {α : Type u} {n : Nat} (x : α) (xs : Vec α n) :
    Vec.head (Vec.cons x xs) = x := rfl

theorem list_append_associative {α : Type u} (xs ys zs : List α) :
    (xs ++ ys) ++ zs = xs ++ (ys ++ zs) := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
      simp [ih]

theorem list_length_append {α : Type u} (xs ys : List α) :
    (xs ++ ys).length = xs.length + ys.length := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
      simp [ih, Nat.succ_add]

class HasUnit (α : Type u) where
  unit : α

instance : HasUnit Nat where
  unit := 1

def unitOf (α : Type u) [HasUnit α] : α := HasUnit.unit

theorem unitOfNat : unitOf Nat = 1 := rfl

theorem classical_excluded_middle (P : Prop) : P ∨ ¬ P :=
  Classical.em P

#print axioms identity
#print axioms implication_transitivity
#print axioms and_commutative
#print axioms or_commutative
#print axioms exists_swap
#print axioms equality_symmetric
#print axioms Point.swap_swap
#print axioms Vec.head_cons
#print axioms list_append_associative
#print axioms list_length_append
#print axioms unitOfNat
#print axioms classical_excluded_middle

end UniversityTPiLRuntime
