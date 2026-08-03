# FIN-ABS-004 — official FDIC bank-distress benchmark

## Purpose

FIN-ABS-004 tests whether a point-in-time model can identify FDIC-insured banks that will fail within eight quarters, while controlling false alarms, calibration and entity leakage. Logic Power selected this untouched domain after the SEC breadth path was externally blocked and the PortBench and CLRD challengers were falsified on sealed tests.

Logic Power is only the meta-controller. It is not part of the credit model.

## Official source contract

- FDIC BankFind Suite API documentation: `https://api.fdic.gov/banks/docs/`.
- Financial taxonomy: `https://banks.data.fdic.gov/docs/risview_properties.yaml`.
- Failure taxonomy: `https://banks.data.fdic.gov/docs/failure_properties.yaml`.
- Financial endpoint: `https://api.fdic.gov/banks/financials`.
- Failure endpoint: `https://api.fdic.gov/banks/failures`.
- Quarterly institution-level financial data are publicly available from 1992 onward; historical failures are available from 1934 onward.

Every request URL, HTTP status, response bytes, row count and SHA-256 is recorded. Stage 0 uses no paid data, model API, GCloud, MotherDuck, OCR or crawler.

## Stage 0 — minimum information audit

Before choosing features or training a model, CI must:

1. acquire and hash both official taxonomy files;
2. verify access to a complete failure list;
3. fetch representative quarterly financial records for 1992, 2000, 2008, 2013 and 2025;
4. identify stable fields present across those periods;
5. count failures by year and determine whether train, validation and test windows contain enough positive entities;
6. test that `CERT` and report date form a unique bank-quarter key;
7. verify that every candidate label can be constructed using a failure date strictly after the information date;
8. emit a fail-closed recommendation: `PROCEED`, `REDESIGN`, or `STOP`.

Stage 0 cannot increase the absolute Finance score.

## Candidate forecasting contract

If Stage 0 passes, the benchmark is preregistered as follows:

- observation unit: FDIC certificate × quarter;
- outcome: bank failure within the next eight quarters;
- one observation per bank per quarter, with all features known on the reporting date;
- entities remain disjoint between training, model selection and the final test whenever a certificate appears in multiple periods;
- institutions entering through merger, charter change or assistance transactions are not silently relabeled as failures;
- failures without an eligible prior financial history are counted but excluded by a fixed rule.

The exact temporal windows will be selected only from Stage 0 event counts, using the earliest feasible contiguous train/validation/test split and then frozen before feature engineering.

## Strong baselines

1. constant failure-rate forecast by training vintage;
2. transparent CAMELS-like score using capital, asset quality, earnings and liquidity ratios available in the official taxonomy;
3. regularized logistic regression;
4. discrete-time survival logistic regression;
5. validation-best baseline selected before test.

## Challenger family

Only a small finite family may compete on validation data:

- monotonic gradient boosting with class weighting;
- monotonic gradient boosting with survival-horizon weights;
- calibrated ensemble of survival logistic regression and monotonic boosting.

Feature names, monotonic directions, missingness rules, class weights and calibration method must be frozen before opening the final test.

## Primary metrics

- area under the precision-recall curve;
- recall at fixed false-positive rates of 0.5%, 1% and 2%;
- precision among the top 1% and top 2% of risk scores;
- Brier score and calibration error;
- expected cost under a preregistered false-negative/false-positive loss ratio;
- lead time from first alarm to failure;
- stability by asset-size group, charter and crisis/non-crisis period.

## Non-compensable gates

A future full benchmark must pass all of the following:

1. official source hashes and taxonomy are exact;
2. zero future-information leakage and zero bank-quarter duplicates;
3. enough positive failures in each frozen evaluation window;
4. challenger test AUPRC exceeds the strongest baseline by at least 5% relatively;
5. challenger recall at 1% false-positive rate is strictly higher;
6. challenger Brier score and calibration error are no worse;
7. improvement persists in both crisis and non-crisis subsets when each has enough events;
8. entity/time split, predictions, metrics and score reproduce independently;
9. source, label, split, metric and score forgeries are rejected.

## Absolute score contract

A full independent PASS may add at most:

- world-SOTA superiority: `+5`;
- historical originality: `+0`;
- cross-domain generality: `+5`;
- external validation and impact readiness: `+8`;
- rigor and reproducibility: `+2`;
- autonomous growth: `+0`.

Maximum delta: **+20 absolute points**. Stage 0 awards zero. The experiment cannot establish universal banking superiority, regulatory fitness, solvency, fraud, misconduct or historical priority.

## Falsification

The route is stopped or redesigned if official access is unstable, taxonomy fields are not historically comparable, positive events are insufficient for a sealed evaluation, labels cannot be constructed without structural ambiguity, or the strongest baseline wins on the frozen test.
