# Fresh USAspending query2–4 — official blind result

**Verdict:** `FAIL` — `0/3`

**Score:** `465/1000` — no promotion points.

| Query | Frozen answer | Official result | Diagnosis |
|---|---:|---:|---|
| California recipients, awards > $1M | `6` | `75` | UEI-to-recipient state entity resolution discarded valid awards. |
| Distinct recipient UEIs in NAICS 33 | `560` | `601` | NAICS corruption normalization remained incomplete. |
| Highest proportion of awards > $1M, agencies with ≥10 awards | Department of Defense | Department of Homeland Security | Planner optimized total qualifying amount, not within-agency proportion. |

## Integrity

- Run `31002739905`, attempt `1`, completed successfully.
- Candidate SHA-256 `a0afa1d615b138e46d588401d6c228ad8dd5992033abfc3486b30e2aff633976`.
- Answers were sealed before validator or ground-truth checkout.
- Each validator executed once.
- Artifact `8929063990`; ZIP SHA-256 `c6b4c26d0e93a44329e7e98ac6f806668274258b4faa1a73351c8b224abf5a39`.
- No retuning, merge, novelty points, GCloud, or paid compute.

Queries 2–4 are exposed and retired from promotion. A successor must learn these general failure classes, freeze, and use fresh queries 5–7.
