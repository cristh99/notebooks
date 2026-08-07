# Stage 09 real-data minimum-cell canary

This package executes exactly one bounded Stage 09 canary over the externally verified two-row Semantic snapshot from PR #149 while preserving the preregistered Stage 09 contract from PR #143.

The legacy analysis contract names `semantic-snapshot/2`; the exact input is `semantic-snapshot/3`. `COMPATIBILITY_BINDING.json` authorizes only the exact bound PR #149 snapshot, preserves the contract population, hypothesis, statistics, minimum-cell threshold, role separation and missingness, and performs no data transformation. The only categorical adapter is the explicit case-only `open → OPEN` / `direct → DIRECT` mapping required by the preregistered groups.

Observed result: one eligible `CONTRACT / CONTRACT_VALUE / CONTRACT_DATE` row, one excluded `PAYMENT` row, no DIRECT row, and no reported `low_competition` outcome because `bid_count` is not reported. The preregistered Fisher analysis therefore terminates `ANALYSIS_NOT_EVALUABLE` before estimation: minimum-cell, complete-outcome and both-group gates all fail.

No p-value, effect estimate, confidence interval, adjusted value, outlier ranking, association promotion, causal claim, wrongdoing label, cross-source relationship assertion or documentary claim is emitted. Stage 10 remains blocked. External cost is `USD 0.00`; production and merge are unchanged.
