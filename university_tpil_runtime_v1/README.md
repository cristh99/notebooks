# University TPiL Lean runtime v1

This capsule closes one narrowly defined university-knowledge gate: execute representative mechanisms from *Theorem Proving in Lean 4* in the real Lean kernel and build the official pinned source projects.

## Frozen source

- Official repository: `leanprover/theorem_proving_in_lean4`
- Commit: `63fad08fcd5f4f3b8b0464561e2fa252671296b9`
- Official examples toolchain: `leanprover/lean4:v4.26.0`
- Official book toolchain: `leanprover/lean4:v4.27.0-rc1`
- Exact Git object bindings live in `SOURCE_LOCK.json`.

## Gates

1. Verify the official commit, tree, toolchain blobs, lakefiles and manifest.
2. Compile `TPiLKernelExercises.lean` with the pinned book toolchain.
3. Expose proof dependencies with `#print axioms`.
4. Reject any `sorry`, `admit`, or new axiom declaration in the scoped exercise file.
5. Require `NegativeControl.lean` to fail kernel checking.
6. Build the official `examples` Lake project at its pinned toolchain.
7. Build the official `book` Lake project at its pinned toolchain.
8. Emit a deterministic report and SHA-256 ledger as a GitHub Actions artifact.

## Scope boundary

A passing run establishes real kernel execution for this capsule and successful builds of the pinned official projects. It does **not** establish that every chapter exercise was solved, that Cambridge or UCL course materials were exhausted, or that the full book has been mastered. The corresponding university resource therefore remains open beyond this scoped runtime gate.
