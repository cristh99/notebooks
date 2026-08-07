# Data Science v14.2 — bounded real Analyze canary

This successor consumes the exact externally signed two-row Semantic snapshot from PR #149 and preserves the noncompensable statistical and claim gates from the exact canonical `ANALYSIS_CONTRACT.json` in PR #143.

The historical PR #143 `capsule.zip` is not executable evidence: its exact 13,116-byte Git blob is not a valid ZIP and its observed SHA-256 differs from the historical declared digest. This defect is retained explicitly as `PR143_PACKAGE_INTEGRITY_DEFECT`; the capsule and its historical 40-test claim are not reused. Instead, this successor pins the exact canonical contract and runs a new independent 40-test conformance suite over its population, hypothesis, baseline, minimum-cell, uncertainty, multiplicity, negative-control, missingness and claim guards.

Only `CONTRACT / CONTRACT_VALUE / CONTRACT_DATE` records are eligible. The single payment record is reported as excluded and is never aggregated with the contract. The eligible contract population has one `OPEN` record, zero `DIRECT` records, null `bid_count`, and null `low_competition`; the preregistered minimum cell size is five. Therefore the only valid terminal is `ANALYSIS_NOT_EVALUABLE / NOT_EVALUABLE_MIN_CELL_SIZE`.

No Fisher test, p-value, effect, interval, FDR adjustment, negative-control claim, outlier ranking, model fit, causal claim, wrongdoing claim, public ranking, relationship validation, or Stage 10 promotion is emitted. This is one bounded conformance canary, not a scientific finding or corpus-wide validation.
