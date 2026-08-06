# Harvard CS1200 deep source audit v1

This capsule advances the university handoff by closing one narrow, verifiable layer of **CS1200 — Introduction to Algorithms and Their Limitations**: the complete public-source inventory and executable-source preflight at a frozen official commit.

## Frozen source

- Official repository: `Harvard-CS-1200/2026-Spring`
- Commit: `0b967fe320ecf2141a6f3b8165d3d096c99fb3ac`
- Git tree: `de8ba1477998a406b2d747bd680a8728b40435b0`
- Coordination: `COORD-2026-08-06-PARALLEL-V2`

## Four disjoint audit groups

1. problem sets `ps0`–`ps3`;
2. problem sets `ps4`–`ps7`;
3. problem sets `ps8`–`ps10`;
4. lectures and SRE sender/receiver documents.

The audit computes a SHA-256 manifest, checks the frozen Git binding, verifies the expected public corpus, parses every Python file, counts public test functions and assertions, records placeholders and dependency declarations, and repeats the scientific payload to confirm deterministic replay.

## Acceptance boundary

A PASS means only:

- the source commit/tree were verified;
- the public corpus was inventoried without missing expected groups;
- all Python sources passed syntax compilation;
- the independent replay reproduced the same normalized report;
- the receipt and evidence ledger verified by SHA-256.

It does **not** mean that the 11 problem sets were solved, that tests passed against completed student implementations, that Canvas/private graders were accessed, or that Harvard CS1200 or Harvard University is complete. Those require separate, public, problem-set-level gates with failures retained in the denominator.

## Guardrails

- zero paid services;
- draft PR only; never merge automatically;
- no copying syllabi as a substitute for absorbed knowledge;
- no target deletion, hidden failure, or relaxed gate;
- public source only; no solutions, private rubrics, Canvas, or credentials.
