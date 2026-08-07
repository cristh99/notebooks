# Harvard CS1200 PS8 — real Glucose runtime lane

This draft lane closes the runtime gap left by the earlier scoped PS8 core. It executes the exact public source at `Harvard-CS-1200/2026-Spring@0b967fe320ecf2141a6f3b8165d3d096c99fb3ac` with a real PySAT `Glucose3` backend, preserves every public timeout in the denominator, cross-checks scientific results independently, and replays the three frozen DIMACS graphs.

## Frozen source

Exact blobs and runtime parameters are recorded in `SOURCE_LOCK.json`. The workflow verifies the official commit and every relevant source/DIMACS blob before execution.

## Gates

1. Replace only the official `ps8.py` in an isolated checkout; never edit the upstream repository.
2. Encode 3-coloring with exactly three SAT variables per vertex, exactly-one color constraints, and edge-conflict clauses.
3. Run the exact `ps8_tests.py 3` public suite. Functional failures fail the lane; public timeouts remain visible because the assignment explicitly treats some timeouts as expected benchmark evidence.
4. Run the exact `ps8_experiments.py` grid with its one-second per-case timeout and retain all rows.
5. Compare Glucose3 with Minisat22 on 1,100 exhaustive graphs, 1,000 deterministic random graphs, 256 exhaustive 3-D matching instances, 500 deterministic random 3-D instances, and the three official DIMACS graphs.
6. Require serial/parallel scientific payload parity and two negative controls.
7. Emit a receipt and SHA-256 ledger, then replay the artifact in a clean GitHub Actions workspace.

## Scope boundary

A passing run establishes the real public PySAT/Glucose runtime, public-test replay, official experiment grid, DIMACS execution, and independent solver/oracle checks. It does **not** claim a private grader result, official grade, autobiographical reflection, optional k-matching completion, complete problem set, complete course, or complete university.

The pull request remains draft and must not be merged automatically.
