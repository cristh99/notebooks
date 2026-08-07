# Harvard CS1200 PS6–PS10 public-source preflight v1

This capsule advances the University handoff through five disjoint public-source lanes while preserving the corrected data model: one canonical course resource, multiple curricular uses and multiple integration/validation events.

## Frozen source

- Repository: `Harvard-CS-1200/2026-Spring`
- Commit: `0b967fe320ecf2141a6f3b8165d3d096c99fb3ac`
- Tree: `de8ba1477998a406b2d747bd680a8728b40435b0`
- Lanes: `ps6`, `ps7`, `ps8`, `ps9`, `ps10`
- Coordination authority: Notion page `COORD-2026-08-06-PARALLEL-V2`

## What the gate proves

For each problem set, two independently cloned source trees must produce identical:

1. full file/SHA-256 manifests;
2. Python syntax results without importing optional dependencies;
3. LaTeX obligation inventories, including optional, reflection and survey signals;
4. counts of tests, TODOs, `pass` nodes and explicit `NotImplementedError` stubs.

Five GitHub Actions jobs execute in parallel. A sixth aggregate job requires all five receipts and emits a combined SHA-256 ledger.

## What the gate does not prove

A green run is only `PASS_SCOPED_SOURCE_PREFLIGHT`. It does not mean the problem sets were solved, public or private tests passed, Gradescope/Canvas was accessed, the course was completed or Harvard knowledge was exhausted. Personal reflections and surveys are never fabricated.

## Next valid gate

Use the extracted technical obligations to open scoped resolution lanes with explicit oracles, independent replay and retained failures. Promote reusable knowledge to Notion; keep code and receipts in GitHub. Additional paid cost: USD 0.
