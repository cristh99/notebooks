# Byzantine Open-World Power v1 — public clean-room replay

Independent, readable implementation reconstructed from the public adversarial contract. It does **not** copy private source code, private workspace content, repository internals, credentials, paths, or private metadata.

## What it checks

- distinct trust roots instead of source aliases;
- dependency-aware support by maximum root↔dependency matching;
- exact Byzantine envelope and quorum intersection;
- sybil aliases and correlated mirrors;
- equivocation, stale/future replay, invalid signatures and unauthorized roots;
- poisoning lineage, missing/cyclic ancestry, revocation and deterministic recomputation;
- evaluator compromise;
- adaptive acquisition of an independent source;
- honest blocked/impossible/abstain terminals.

## Reproduce

```bash
cd byzantine_open_world_power_v1_public
PYTHONPATH=. python -m compileall -q byzantine_open_world_power_v1 tests
PYTHONPATH=. python -m byzantine_open_world_power_v1.replay
PYTHONPATH=. python -m byzantine_open_world_power_v1.verify
node byzantine_open_world_power_v1/verify.js
PYTHONPATH=. python -m unittest -v tests.test_replay
```

Expected clean-room result:

- **72/72** frozen scenarios;
- **27/27** adversarial tests;
- Python verifier PASS;
- Node verifier PASS;
- ordinary tampering rejected;
- rehashed semantic forgery rejected;
- deterministic receipt `cf9328807097884c37a2ff0652ed4475f961212ed692c0a32320f78fab26b12e`.

## Claim boundary

This establishes public reproducibility of a finite synthetic adversarial grammar. It does not establish large-scale Byzantine tolerance, complete semantic-deception detection, safe self-modification, real-world utility, universal superiority, scientific priority, or global `1000/1000`.
