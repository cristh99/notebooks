# Finance 1000 — Logic Power Problem Solver public replay

This capsule independently reconstructs the Finance 1000 case compiled by **Logic Power Problem Solver v1**.

## Strict result

```text
score = 820 / 1000
open = G07, G09
terminal status = BLOCKED
```

The score is the sum of independently evidenced PASS gates. It is not a maturity estimate and cannot be raised by adding pages, code volume or synthetic demonstrations.

## Typed route

The Problem IR classifies the program as:

- planning;
- robust decision under unknown state;
- active information acquisition;
- verification.

`finite_dynamic_programming` fails closed because the transition model is partial. The selected eligible method is `robust_minimax_regret`; `logic_exact` remains an eligible verification layer.

## Selected portfolio

```text
parallel_g07_g09_program
```

1. finish the strong-baseline documentary holdout and clean independent replay for G07;
2. finish systematic prior-art comparison and independent replication for G09.

More internal theory receives negative planning value because it cannot close either gate.

## Verification

- standard-library Python reconstruction;
- deterministic Problem IR and certificate;
- unit and adversarial tests;
- independent dependency-free Node semantic verifier;
- raw tamper rejection;
- rehashed semantic forgery rejection;
- public GitHub Actions artifact.

## Boundary

The planning units used to choose work are not Finance score points. Only a gate that meets its declared evidence contract changes the 1000-point score. The capsule does not claim that G07 or G09 already pass.
