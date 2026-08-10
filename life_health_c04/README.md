# C04 synthetic oxygen transport artifact

Deterministic **synthetic-only** reproducibility artifact for the Tree of Life C04 oxygen production/transport protocol. It is not clinical data, not a diagnostic model, not a causal estimate, and not a training or selection recommendation.

- Physics identity: Fick principle `VO2 = Q * (CaO2 - CvO2)` with explicit units.
- Synthetic fixtures: rest, exercise, anemia-like and altitude-like parameter regimes; these are test fixtures, **not reference intervals**.
- Seed: `20260810`; no third-party Python packages.
- Train/test split is by synthetic subject row inside each scenario.
- `sex_observed` is metadata and has no claimed causal meaning; the sex-residual model is a falsifiable predictive comparison only.
- Independent replay: Node.js recomputes Fick values from the serialized CSV without importing Python code.
- Repository license: Apache-2.0. No third-party patient dataset is used.

Run: `python3 generator.py && python3 tests.py && python3 run.py && node replica.mjs output/c04_synthetic.csv`.
