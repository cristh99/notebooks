# FIN-ABS-004 — official FDIC bank-distress benchmark

## Purpose

FIN-ABS-004 tests whether a point-in-time model can identify FDIC-insured banks that will fail within eight quarters, while controlling false alarms, calibration, entity leakage and crisis instability. Logic Power selected this untouched domain after the SEC breadth path was externally blocked and the PortBench and CLRD challengers were falsified on sealed tests.

Logic Power is only the meta-controller. It is not part of the credit model.

## Official source contract

- FDIC BankFind Suite documentation: `https://api.fdic.gov/banks/docs/`.
- Financial endpoint: `https://api.fdic.gov/banks/financials`.
- Failure endpoint: `https://api.fdic.gov/banks/failures`.
- Quarterly institution-level financial data are publicly available from 1992 onward; historical failures are available from 1934 onward.

Every request URL, status, response byte count and SHA-256 is recorded. The experiment uses no paid data, model API, GCloud, MotherDuck, OCR or crawler.

## Completed Stage 0

The live official contract exposed 161 financial fields and 33 failure fields. Five representative quarters from 1992 through 2025 and all 4,115 historical failure records were acquired. `CERT × REPDTE` was unique in every sample and the event counts were sufficient to proceed.

Stage 0 adds no absolute score points.

## Temporal panel

- observation unit: FDIC certificate × quarter;
- outcome: bank failure in the next 730 days;
- assistance transactions remain separate from failure;
- features use only information available on or before the report date;
- original temporal windows:
  - train: 1992-12-31 through 2002-12-31;
  - validation: 2005-03-31 through 2006-12-31;
  - test: 2009-03-31 through 2011-12-31;
- gaps ensure every eight-quarter outcome is observable before the next evaluation window.

The raw temporal panel contains 630,365 bank-quarters. A preflight correctly rejected it because thousands of continuing banks appeared in more than one temporal split. The sealed test therefore remained unopened.

## Immutable entity-disjoint correction

Before model selection, every `CERT` is assigned a SHA-256 bucket using the fixed seed `FIN-ABS-004-ENTITY-SPLIT-V1`. A row is retained only when its original temporal window matches its entity bucket:

- train: buckets 0–34;
- validation: buckets 35–74;
- test: buckets 75–99.

The rule uses only `CERT` and the original temporal split. It does not inspect feature values, model scores, predictions or sealed-test performance.

Expected retained cohort from the frozen source panel:

- train: 162,519 rows, 5,492 entities, 48 positive entities;
- validation: 28,808 rows, 3,789 entities, 12 positive entities;
- test: 23,501 rows, 2,077 entities, 102 positive entities;
- entity overlap: zero.

Python constructs and hashes the derived panel. A fail-closed preflight and an independent Node boundary verifier bind the entity-split and preflight receipts into the final benchmark certificate.

## Strong baselines

1. constant failure-rate forecast by training vintage;
2. transparent CAMELS-like score using capital, asset quality, earnings and liquidity ratios;
3. regularized logistic regression;
4. discrete-time survival logistic regression;
5. validation-best baseline selected before test.

## Challenger family

Only this finite family may compete on validation data:

- monotonic gradient boosting with class weighting;
- monotonic gradient boosting with survival-horizon weights;
- calibrated ensemble of survival logistic regression and monotonic boosting.

Feature names, monotonic directions, missingness rules, loss ratio, calibration and selection rule were frozen before a valid sealed test could open.

## Primary metrics

- area under the precision-recall curve;
- recall at false-positive rates of 0.5%, 1% and 2%;
- precision among the top 1% and 2% of risk scores;
- Brier score and calibration error;
- expected cost under a 100:1 false-negative/false-positive loss ratio;
- lead time from first alarm to failure;
- stability in crisis and non-crisis subsets;
- entity-cluster bootstrap.

## Non-compensable gates

A future full benchmark must pass all of the following:

1. official source and panel hashes are exact;
2. zero future-information leakage and zero bank-quarter duplicates;
3. zero entity overlap among train, validation and test;
4. enough positive failure entities and rows in every frozen split;
5. challenger test AUPRC exceeds the strongest baseline by at least 5% relatively;
6. challenger recall at 1% false-positive rate is strictly higher;
7. challenger Brier score and calibration error are no worse;
8. expected-cost reduction is at least 5%;
9. improvement persists in crisis and non-crisis subsets when evaluable;
10. entity-bootstrap lower 95% bound is positive;
11. split, predictions, metrics, receipts and score survive independent replay;
12. source, label, split, metric and score forgeries are rejected.

## Absolute score contract

A full independent PASS may add at most:

- world-SOTA superiority: `+5`;
- historical originality: `+0`;
- cross-domain generality: `+5`;
- external validation and impact readiness: `+8`;
- rigor and reproducibility: `+2`;
- autonomous growth: `+0`.

Maximum delta: **+20 absolute points**. No Stage 0, acquisition, split construction, test execution or Python-only candidate result can increase the score by itself. The canonical absolute Finance score remains **423/1000** until every required independent gate passes.

## Falsification

The route is falsified or blocked if the strongest baseline wins, any non-compensable gate fails, the entity split lacks enough failures, the result is unstable across regimes, or the evidence cannot be reproduced independently. No parameter, feature, bucket boundary or threshold may be retuned against an observed sealed test.
