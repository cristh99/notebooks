# Data Science v14.2 — bounded real Analyze canary

This successor consumes the exact externally signed two-row Semantic snapshot from PR #149 and applies the unchanged noncompensable gates from the Stage 09 reference contract in PR #143.

Only `CONTRACT / CONTRACT_VALUE / CONTRACT_DATE` records are eligible. The single payment record is reported as excluded and is never aggregated with the contract. The eligible contract population has one `OPEN` record, zero `DIRECT` records, null `bid_count`, and null `low_competition`; the preregistered minimum cell size is five. Therefore the only valid terminal is `ANALYSIS_NOT_EVALUABLE / NOT_EVALUABLE_MIN_CELL_SIZE`.

No Fisher test, p-value, effect, interval, FDR adjustment, negative-control claim, outlier ranking, model fit, causal claim, wrongdoing claim, public ranking, relationship validation, or Stage 10 promotion is emitted. This is one bounded conformance canary, not a scientific finding or corpus-wide validation.
