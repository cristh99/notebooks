# Logic Power v10 — public verification capsule

This branch is an isolated, unmerged CI capsule for the private Logic Power v10 implementation.

- Private source repository: `cristh99/my_first_repository`
- Private source branch: `agent/logic-power-v10-active-experiment`
- Bound private head: `ba10d0edc7eb20d499d0481fda2537e782b6efb2`
- Deterministic source archive SHA-256: `ad2c363afb3fe20aa093565f278c690d423611e8270e9ad9b1491dbbdf218c31`
- Base64 transport SHA-256: `9d138ecd964e91e4db86fd5b663bb40d0599443f238d03b58b0a3418bca0dabb`

The workflow decodes the source capsule, verifies every file hash, runs the exact Python test suite and both independent certificate verifiers, rejects a tampered certificate, executes the two TLA+/TLC terminal models, compiles the Lean boundary without Mathlib or `sorry`, and emits a reproducible evidence package.

This capsule must remain isolated and must not be merged into the notebooks project. Its sole purpose is free public CI replication while GitHub Actions is unavailable in the private source repository.
