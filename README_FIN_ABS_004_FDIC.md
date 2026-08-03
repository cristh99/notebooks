# FIN-ABS-004 — official FDIC bank-distress benchmark

## Purpose

FIN-ABS-004 tests whether a point-in-time model can identify FDIC-insured banks that will fail within eight quarters while controlling false alarms, calibration and temporal leakage. Logic Power selected this untouched domain after the SEC breadth path was externally blocked and the PortBench and CLRD challengers were falsified on sealed tests.

Logic Power is only the meta-controller. It is not part of the credit model.

## Official source contract

- FDIC BankFind Suite API documentation: `https://api.fdic.gov/banks/docs/`.
- Live API base: `https://banks.data.fdic.gov/api`.
- Financial endpoint: `/financials`.
- Failure endpoint: `/failures`.
- Complete acquisition records include URL, HTTP status, bytes, row count and SHA-256.

The two former YAML-taxonomy URLs now return the official API-documentation HTML rather than YAML. Stage 0 therefore binds fields to the live one-record API schema and verifies them again across representative quarters instead of pretending HTML is a taxonomy.

## Stage 0 result

Public CI returned `PROCEED`:

- live financial contract: 161 fields;
- live failure contract: 33 fields;
- complete failure records: 4,115;
- representative financial quarters: 1992, 2000, 2008, 2013 and 2025;
- stable required fields: `CERT, REPDTE, NAME, ASSET, DEP, EQ, NETINC, ROA, ROE`;
- duplicate `CERT × REPDTE` keys: zero in every sample;
- candidate failure counts: 301 train-era, 33 validation-era and 472 test-era.

Stage 0 awards no absolute points.

## Frozen forecasting contract

### Observation and label

- observation unit: FDIC certificate × quarter;
- positive outcome: a record with `RESTYPE = FAILURE` and the same `CERT` fails strictly after the report date and within the next 730 days;
- `RESTYPE = ASSISTANCE` is excluded from the positive class and reported separately;
- one record per `CERT × REPDTE`;
- a failure without eligible prior financial data is counted but excluded by a fixed rule;
- merger, charter change, inactivity or assistance is never silently relabeled as failure.

### Temporal windows

Every label horizon ends before the next evaluation window begins:

- **train observations:** 1992-12-31 through 2002-12-31; outcomes observed through 2004-12-31;
- **validation observations:** 2005-03-31 through 2006-12-31; outcomes observed through 2008-12-31;
- **sealed test observations:** 2009-03-31 through 2011-12-31; outcomes observed through 2013-12-31.

Banks may recur over time because a deployed supervisor scores the same institution repeatedly; all inference and confidence intervals are clustered by `CERT`, and no future quarter or future label contributes to features.

### Frozen raw fields

The acquisition request is limited to:

`CERT, REPDTE, NAME, ASSET, EQ, DEP, NETINC, ROA, ROE, LNLSNET, NCLNLS, NCO, LIQASSET, BRO, FREP, SC, NIM, RBCT1CER, RBCT1J, RBCT1R, LNATRES, DEPBRWOFF, DEPLSNB, CHARTER, STALP, STNAME, SPECGRP, BKCLASS, ACTIVE`.

### Frozen derived features

Only current or trailing information is allowed:

- log assets;
- equity/assets;
- deposits/assets;
- net loans/assets;
- noncurrent loans/net loans;
- net charge-offs/net loans;
- liquid assets/assets;
- brokered deposits/deposits;
- fed-funds-and-repos/assets;
- securities/assets;
- net income/assets;
- ROA, ROE and NIM;
- Tier 1 common, leverage and risk-based capital ratios when reported;
- one-year growth in assets, deposits, equity and loans;
- four-quarter means and standard deviations for ROA and noncurrent-loan ratio;
- negative-income and declining-capital indicators;
- explicit missingness indicators for every numeric feature.

Ratios with zero or nonpositive denominators are missing, not zero. Continuous features are winsorized using training-only 0.5% and 99.5% bounds, then median-imputed from training data only.

## Strong baselines

1. `CONSTANT_RATE` — training-vintage failure rate;
2. `CAMELS_LITE` — transparent fixed-direction score using capital, asset quality, earnings, liquidity and growth;
3. `LOGISTIC_L2` — regularized logistic regression;
4. `SURVIVAL_LOGIT` — horizon-weighted discrete-time logistic regression;
5. `VALIDATION_BEST_BASELINE` — lowest validation expected cost, breaking ties by higher AUPRC, lower Brier score and method name.

## Challenger family

Only these preregistered variants may compete on validation data:

- `MONOTONIC_HGB` — monotonic histogram gradient boosting with balanced weights;
- `MONOTONIC_HGB_HORIZON` — the same model with greater weight on failures occurring within four quarters;
- `CALIBRATED_ENSEMBLE` — 50/50 survival-logit and monotonic-HGB probabilities followed by Platt calibration on validation data.

Fixed hyperparameters: maximum depth 3, learning rate 0.05, 200 iterations, minimum leaf size 50 and L2 regularization 1.0. No model, feature, threshold or split changes after the sealed test is opened.

## Primary metrics

- area under the precision-recall curve;
- recall at fixed false-positive rates of 0.5%, 1% and 2%;
- precision among the top 1% and top 2% of scores;
- Brier score and ten-bin expected calibration error;
- expected cost with false-negative cost 100 and false-positive cost 1;
- median lead time from first alarm to failure;
- stability by asset-size tercile, charter and crisis/non-crisis period;
- bank-cluster bootstrap confidence intervals.

## Non-compensable gates

A full benchmark passes only when all gates pass:

1. official source hashes and live schema are exact;
2. zero future-information leakage and zero bank-quarter duplicates;
3. at least 20 positive validation failures and 100 positive test failures;
4. challenger test AUPRC exceeds the strongest baseline by at least 5% relatively;
5. challenger recall at 1% false-positive rate is strictly higher;
6. challenger Brier score and calibration error are no worse;
7. challenger expected cost is at least 5% lower;
8. the paired bank-cluster-bootstrap lower 95% bound for cost improvement is positive;
9. improvement persists in both crisis and non-crisis subsets when each has at least 20 positives;
10. Python and an independent Node implementation reproduce labels, split, predictions, metrics and score;
11. source, label, split, metric and score forgeries are rejected.

## Absolute score contract

A full independent PASS may add at most:

- world-SOTA superiority: `+5`;
- historical originality: `+0`;
- cross-domain generality: `+5`;
- external validation and impact readiness: `+8`;
- rigor and reproducibility: `+2`;
- autonomous growth: `+0`.

Maximum delta: **+20 absolute points**. Until full independent verification, the absolute Finance score remains **423/1000**.

## Boundary

A PASS would establish a bounded retrospective early-warning result on official FDIC data. It would not establish regulatory approval, current-bank solvency, misconduct, fraud, causality, live supervisory fitness, universal banking superiority or historical priority.
