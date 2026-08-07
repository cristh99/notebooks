# Stage 09 — bounded real Analyze canary

This successor consumes the exact externally verified Semantic snapshot from PR #149 and executes only the preregistered eligibility gate from Analyze PR #143.

The Semantic input contains two source-native events (`CONTRACT`, `PAYMENT`), while the registered Analyze population is `CONTRACT / CONTRACT_VALUE / CONTRACT_DATE` and requires at least five evaluable observations in each registered method group (`DIRECT`, `OPEN`). The canary must therefore terminate `ANALYSIS_NOT_EVALUABLE / NOT_EVALUABLE_MIN_CELL_SIZE` without emitting a p-value, effect estimate, confidence interval, q-value, ranking, causal statement, or wrongdoing label.

The payment event, cross-source relationship, quarantined IAIP document, and raw identities are excluded. This is a bounded real-data gate check, not a statistical finding or a scale-up. Stage 10 remains blocked; production is unchanged; external cost is USD 0.00.
