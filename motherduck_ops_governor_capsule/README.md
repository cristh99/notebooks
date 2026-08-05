# MotherDuck Operations Governor — Public Verification Capsule

This capsule evaluates a frozen, read-only candidate policy for governing MotherDuck operations. It is isolated from production, performs no network calls, writes no external state, and spends no money.

## Claim boundary

The capsule checks only the declared finite grammar:

- active leases must be protected;
- unauthorized, irreversible, or receipt-destroying operations must be rejected;
- deterministic failures, terminal monitors, superseded definitions, recurring one-shot tasks, repeated `NOOP` runs, and schedule overlap must route to the declared terminal;
- ambiguous cases must remain `UNKNOWN`;
- identical semantic inputs must produce identical packets and digests.

It does **not** establish production authority, hidden real-world out-of-sample performance, universal safety, general agent superiority, or `Verified` lifecycle status.

## Sources under evaluation

- Private candidate branch: `cristh99/my_first_repository@agent/motherduck-ops-governor-v1`
- Private PR: `cristh99/my_first_repository#112`
- Candidate source path: `skills/motherduck-ops-governor/reference.py`
- Frozen private receipt path: `evidence/motherduck-ops-governor-v1/candidate-evaluation.json`
- Logic Power v10: `cristh99/my_first_repository#53`
- Logic Power Problem Solver: `cristh99/my_first_repository#84`
- Skill Power Foundation: `cristh99/my_first_repository#110`

The public `candidate.py` is a frozen replica of the read-only candidate evaluator. `oracle.py` is independently structured and expresses the same bounded policy as an ordered decision table. `verify.py` compares both across frozen fixtures and an exhaustive finite grammar, then compares several unsafe or weak baselines.

## Run locally

```bash
python motherduck_ops_governor_capsule/verify.py
python -m unittest discover -s motherduck_ops_governor_capsule -p 'test_*.py' -v
```

Outputs are written only to `motherduck_ops_governor_capsule/artifacts/`.
