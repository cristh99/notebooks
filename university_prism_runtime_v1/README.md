# University PRISM runtime v1

This capsule closes one scoped formal-runtime gate for the university knowledge corpus: execute probabilistic model checking in the real PRISM binary and compare the results with independent mathematical oracles.

## Frozen runtime

- Official repository: `prismmodelchecker/prism`
- Release: `v4.10.1`
- Linux x86 asset SHA-256: `9f2135b1d49293cdc9b16b1756a24f99beff320b78134825c1f477f43942ab17`
- Engine: explicit

## Models and oracles

- DTMC eventual reachability: `0.4`.
- MDP minimum/maximum reachability: `0.2` / `0.9`.
- DTMC expected reward until target: `2.0`.
- CTMC time-bounded reachability at `t=1`: `1-exp(-2)`.
- CTMC steady-state probability: `2/3`.
- Invalid probability distribution: must be rejected.

The quantitative suite runs once serially and once through four independent parallel processes; parsed scientific results must match each other and the frozen oracles.

## Scope boundary

A passing run establishes the real PRISM runtime for these finite DTMC, MDP, CTMC and reward cases. It does not establish completion of the full PRISM manual, all Oxford course material, PTA, POMDP, interval models, stochastic games or every supported logic.
