# ACIC 2016 sealed causal-transfer gate

This capsule tests the next unresolved hypothesis after the official ResNet Bit Flip PASS:

```text
adaptive_neural_model_analyst
versus
broad_data_science_capability
```

The original verified Logic Power v10 selects the ACIC 2016 external causal benchmark as the minimum-cost separating experiment. It uses real covariates with simulated treatment and potential outcomes, so effect estimates can be checked against ground truth without giving that truth to the candidate estimator.

## Split

- public development: causallib ACIC instances `1..6`;
- official sealed: instances `7..10`;
- candidate API: covariates, observed treatment, observed outcome only;
- official truth: unavailable until after the public candidate is frozen;
- one official evaluation; no post-hoc retuning.

## Candidate

`estimator.py` implements cross-fitted doubly robust estimation:

- logistic plus boosted propensity ensemble;
- ridge plus boosted outcome ensemble;
- cross-fitted AIPW ATE;
- doubly robust ATT;
- influence-function ATE interval;
- individual-effect predictions;
- overlap and effective-sample-size diagnostics.

## Public gate

The candidate must:

1. remain finite on every public DGP;
2. beat the unadjusted difference in means on ATE RMSE;
3. beat the unadjusted difference in means on ATT RMSE;
4. beat a cross-fitted ridge T-learner on mean PEHE;
5. cover at least half of true ATEs with its 95% intervals;
6. win against the naive estimator on at least half of public instances for both ATE and ATT.

Public success freezes the candidate. The hidden instances are then evaluated once in a separate workflow and any PASS, FAIL, NOT_RUN, or INVALID_RUN is preserved.

## Boundary

A PASS would establish external transfer into causal-effect estimation on a small, independent ACIC sample. It would not establish historical novelty, universal causal identification, or global causal-inference SOTA.
