# Data Science God-Level external gate — AutoLab Adaptive Compression

This capsule uses the **original hash-bound Logic Power v10** as a planner. It does not create a new Logic Power version.

## Original versus specialized extensions

The original is the controlling engine because it has the smallest semantics, independent certificate replay, TLA+/TLC checks, and an axiom-free Lean boundary. The later Data Science extensions are retained only as optional adapters; they do not replace the original planner.

Given three surviving explanations for the local result—NumPy/environment artifact, evaluator exploitation, or a portable external win—the original v10 synthesizes:

```text
1. clean_numpy126_replay
2. evaluator_integrity_redteam
```

`more_internal_tests` has no separating power and is rejected.

## External task

- Benchmark: AutoLab `adaptive_compression`.
- AutoLab source commit: `7aff5fe71dfbe152fb0b8e8ac8087210b4bc27d5`.
- Metric: byte-weighted bits per byte; lower is better.
- Public baseline threshold: `5.0` bpb.
- Public reference: `3.8` bpb.
- Official environment: Python 3.11 and NumPy 1.26.4.
- Seeds fixed before clean execution: `2024`, `20260803`, `314159265`, `271828182`.

The candidate is a frozen online mixture of context models, recency adaptation, period detection, modular recurrence inference, run-length prediction, and nested-tag reconstruction. It does not import filesystem, process, network, reflection, or dynamic-code facilities.

## Local pre-CI evidence

On NumPy 2.3.5, the frozen candidate produced sealed-seed scores `3.5680`, `3.4573`, and `3.5586` bpb; the byte-weighted sealed mean was `3.5270` versus `5.1522` for the paired baseline. These values are provisional until the clean pinned workflow passes.

## Promotion rule

No external-win claim is promoted unless:

1. the original Logic Power v10 certificate selects the clean replay;
2. the candidate hash matches exactly;
3. AutoLab files are fetched from the pinned commit and Git object hashes match;
4. the official subprocess-isolated evaluator is used;
5. every predeclared seed beats `3.8` and its paired baseline;
6. the integrity red-team rejects an invalid-distribution control;
7. the complete report is retained as a GitHub Actions artifact.

The capsule remains draft and unmerged.
