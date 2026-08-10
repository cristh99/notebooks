# C04 provenance and use boundary

- Source contract: Tree of Life C04 protocol in Notion; this repository artifact implements only the synthetic reproducibility path.
- Data source: **none**. Every row is generated deterministically from repository code and seed `20260810`; no patient, athlete, clinical, institutional, or personally identifying dataset is ingested.
- Durable destination: this GitHub branch/commit history.
- Code and documentation are contributed under the repository's Apache-2.0 license.
- Generated CSV is synthetic test output only and is not a clinical reference dataset.
- `sex_observed` is synthetic metadata; no causal interpretation is permitted.
- Allowed claims: software reproducibility, unit/dimension checks, deterministic fixtures, predictive comparison inside this synthetic generator, measurement perturbation sensitivity, and implementation replay.
- Disallowed claims: diagnosis, treatment, training prescription, athlete selection, population physiology estimates, causal sex differences, external validity, or clinical recommendations.
