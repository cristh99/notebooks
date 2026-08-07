# LP-KAL Conformance and Causal-Ablation Benchmark v1

This is a deterministic, dependency-free **mechanistic benchmark** for the Logic Power Knowledge–Action Loop (LP-KAL). It tests whether a governance implementation preserves the declared boundary between Knowledge and Actions across six domains.

## What it tests

The benchmark contains **96 frozen scenarios**: 16 archetypes × 6 domains. It measures unauthorized execution, false promotion of local results into knowledge, hidden commitments, premature closure, temporal violations, stale `DOING`, tampered authority, duplicate creation, authority conflicts, and missing feedback.

It compares:

- full LP-KAL;
- an equally guarded monolithic runtime;
- a rename-only negative control;
- thirteen single-gate ablations.

The monolithic guarded baseline is expected to tie LP-KAL behaviorally. This is deliberate: the benchmark must not manufacture a victory for semantic typing when equivalent runtime checks are present. Type-level superiority requires separate mutation, maintenance, or implementation studies.

## Frozen hypotheses

See `preregistration.json`. The main gates are:

- full LP-KAL: 100% exact conformance, zero violations, 100% positive-case completion;
- every targeted mutant killed in all six domains;
- mutation score 1.0;
- monolithic guarded and rename-only controls tie full LP-KAL;
- deterministic hashes and tamper rejection.

## Run

```bash
python lp_kal_benchmark.py
python -m unittest discover -s tests -v
```

Outputs are written to `reports/`:

- `scenario_manifest.json`;
- `benchmark_summary.json`;
- `benchmark_matrix.csv`;
- `benchmark_receipt.json`.

## Scientific boundary

A PASS means the suite detects the preregistered boundary failures and the complete policy conforms to its own contract. It does **not** establish universal problem-solving superiority, human-preference correctness, LLM superiority, or novelty over BDI, MAPE-K, Knowledge-to-Action, epistemic planning, ReAct/Reflexion, or proof-carrying authorization.

Stage B must implement faithful, equal-budget adapters to external architectures and evaluate real interactive tasks. Stage C must test runtime↔formal refinement and independent reproduction.
