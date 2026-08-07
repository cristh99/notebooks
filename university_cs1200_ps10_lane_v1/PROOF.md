# Harvard CS1200 PS10 — mandatory technical lane

This document closes the public mandatory technical obligations of PS10 under a
source-bound, executable contract. It does not answer the personal reflection,
submit the optional survey, solve the optional NP-hardness part, access a private
grader, assign a course grade, or mark Harvard CS1200 complete.

## 1. Recognizing solvability and unsolvability

### 1a. Which Algorithm Is Faster — solvable

The input promises that Word-RAM programs `P` and `Q` both solve Graph
3-Coloring. Therefore, for the supplied graph `G` and word length `w`, both
executions halt. Simulate `P[w](G)` to completion while counting steps, then do the
same for `Q[w](G)`, and compare the two finite counts. The procedure always
terminates and returns the required yes/no answer.

The promise is essential. Without totality on the supplied input, waiting for one
program to terminate could encode the Halting Problem.

### 1b. TM vs. Word-RAM — solvable, constant answer yes

A polynomial-time Turing machine can be compiled/simulated by a polynomial-time
Word-RAM program with polynomial overhead. Thus, for every promised input machine,
there exists a polynomial-time Word-RAM program that solves all of the same
computational problems. The correct algorithm returns `yes` on every valid input.

This conclusion uses the course’s polynomial-overhead formulation of the Extended
Church-Turing Thesis/strong Turing equivalence; it is not a claim of equal constants
or equal exact runtimes.

### 1c. Waiting for Godot — unsolvable

Reduce `Halts On Empty-RAM`. Given a RAM program `P`, construct `Q_P` as follows:

- on input `Vladimir`, simulate `P` on the empty input; if the simulation halts,
  output `Godot`;
- on input `Estragon`, loop forever;
- on all other inputs, behavior is irrelevant to the target problem.

`Q_P` outputs `Godot` on at least one of the two named inputs iff `P` halts on the
empty input. A solver for Waiting for Godot would therefore solve an unsolvable
problem, so Waiting for Godot is unsolvable.

## 2a. Overflow-free RAM to Word-RAM simulation

Let `maximum = 2^w - 1`.

### Memory handling

Before a read or write to address `a`, call `MALLOC` until the address lies in the
current memory. If the RAM computation halts, it touches finitely many addresses,
uses finitely many constants and reaches finitely many values. A sufficiently large
word length represents all of them and permits the required finite memory growth.

### Addition check

For word operands `x,y`,

`x + y > maximum  iff  x > maximum - y`.

The right side uses subtraction and comparison without executing the overflowing
addition. If it holds, the transformed program loops or deliberately crashes before
the arithmetic command; otherwise it performs the addition safely.

### Multiplication check and source defect

For `y > 0`,

`x*y > maximum  iff  x > floor(maximum/y)`.

The printed algorithm omits the `y=0` branch; literal evaluation divides by zero.
The repaired algorithm first returns “no overflow” when `y=0`, then applies the
quotient test for positive `y`. This is a real edge-case defect, not a change to the
mathematical claim.

### C1

If `P` halts on `x`, choose a word length large enough for all values, addresses,
constants and memory used in that finite execution. No guard fires, and `P'[w]`
simulates every step and halts without crashing. If `P` does not halt, the statement
“`P'[w]` halts without crashing iff `P` halts” is satisfied by any `w` for which the
transformed run does not halt normally; it may loop or deliberately crash at a
would-overflow guard.

### C2

Whenever `P'[w]` halts without crashing, every executed RAM operation was simulated
with the same natural-number result and the same memory/control-flow effect. Hence
its output equals `P(x)`.

### C3

Every addition or multiplication is executed only after its exact guard proves the
result at most `maximum`. Subtraction and division cannot exceed their operands in
the nonnegative RAM semantics. Therefore no arithmetic command actually executed by
`P'[w]` overflows.

Changing line numbers after expanding one source instruction into several target
instructions preserves `GOTO` behavior.

## 2b. ArithmeticOverflow is unsolvable

Reduce `Halts On Empty-RAM`. Given `P`:

1. construct its guarded overflow-free Word-RAM simulation `P'` from Part 2a;
2. run `P'` on the empty input;
3. if it halts normally, set a word to `1` and repeatedly double it until the next
   addition exceeds `2^w-1`.

If `P` halts, there exists a sufficiently large `w` for which `P'[w]` halts normally;
repeated doubling then causes an actual overflow. If `P` does not halt, `P'` never
halts normally for any `w`; its guards prevent execution of an overflowing command,
so the appended doubling phase is never reached. Thus the constructed Word-RAM has
an overflow for some word length iff `P` halts on empty input. A solver for
ArithmeticOverflow would solve `Halts On Empty-RAM`, contradiction.

## 2c. Fixed-word ArithmeticOverflow is solvable

Fix `P` and `w`. A complete machine state consists of:

- current program counter;
- every program variable, each in `[0,2^w-1]`;
- current memory size, bounded by the Word-RAM address space;
- every memory word, also in `[0,2^w-1]`.

The program description, number of variables and word length are finite, so there
are finitely many states. Simulate deterministically:

- if an arithmetic command overflows, return `yes`;
- if the program halts or crashes without overflow, return `no`;
- if a state repeats, determinism implies the future execution repeats forever, so
  return `no`.

This is a terminating decision algorithm, although its state space is enormous and
its runtime need not be polynomial in the bitlength of `w`.

## 2d. Optional NP-hardness

Not claimed. The optional problem is explicitly outside the mandatory lane.

## Validation contract

The executable receipt requires:

1. exact source commit, tree, `ps10.tex` and `ps10.pdf` hashes;
2. exhaustive addition and multiplication checks for word lengths 1 through 10;
3. explicit reproduction of the source’s multiplication-by-zero defect;
4. two independent fixed-word deciders — visited-state and Floyd cycle detection —
   on every three-instruction program in a bounded instruction language and word
   lengths 1 through 3;
5. 15,000 randomly generated terminating RAM programs simulated by a sufficiently
   wide guarded Word-RAM with identical outputs;
6. all smaller-word probes verified to execute no overflowing command;
7. 15,000 positive and 2,000 negative finite analogues of the
   Halting-to-Overflow and Waiting-for-Godot reductions;
8. 15,000 exact runtime comparisons for promised-total programs;
9. identical scientific payloads in serial and four-worker runs;
10. receipt and SHA-256 ledger.

Finite executable analogues validate the constructions and edge conditions; they do
not replace the reduction proofs of undecidability.

## Scope boundary

A green receipt means `PASS_SCOPED_PS10_MANDATORY_TECHNICAL_LANE`. It does not mean:

- optional NP-hardness solved;
- personal reflection answered;
- survey submitted;
- private Gradescope/Canvas grader passed;
- official grade earned;
- PS10 or Harvard CS1200 exhaustively complete.
