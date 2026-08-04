# FIN-ABS-004B — untouched FDIC benchmark with Random Forest

## Purpose

FIN-ABS-004 was honestly falsified on 2009–2011: monotonic boosting improved ranking and crisis cost but worsened Brier calibration and lost in the non-crisis year. FIN-ABS-004B uses that result only as development evidence and moves to an **untouched 2012–2013 test period**.

Logic Power remains the meta-controller. It is not part of any bank-risk model.

## Why a new experiment is required

The published U.S. bank-failure literature identifies Random Forest and cost-sensitive forests as strong comparators, while logistic regression remains a strong interpretable baseline. They were not added retroactively to FIN-ABS-004 because its test had already opened.

FIN-ABS-004B therefore freezes the stronger baseline family before acquiring or evaluating the new test.

## Temporal contract

Outcome: FDIC failure strictly after the report date and within 730 days. Assistance transactions remain separate.

- train observations: 1992-12-31 through 2004-12-31; outcomes visible through 2006-12-31;
- validation observations: 2007-03-31 through 2009-12-31; outcomes visible through 2011-12-31;
- untouched test observations: 2012-03-31 through 2013-12-31; outcomes visible through 2015-12-31.

The prior experiment used observations only through 2011. No 2012–2013 model result has been observed.

## Entity-disjoint rare-event design

Every FDIC certificate receives one immutable SHA-256 bucket using seed `FIN-ABS-004B-ENTITY-SPLIT-V1`.

- train: buckets 0–19;
- validation: buckets 20–29;
- test: buckets 30–99.

The large test share is preregistered because only 75 raw failures occurred in 2012–2013. The rule uses only `CERT` and original temporal window; it cannot inspect features, labels, predictions or performance.

## Stage 0

Before model construction, CI must:

1. reconstruct all official bank-quarter rows required by the three windows;
2. construct 730-day failure labels and separate assistance;
3. freeze the entity-disjoint cohort;
4. prove strict temporal order, zero `CERT × REPDTE` duplicates and zero entity overlap;
5. require at least 30 positive train entities, 10 validation entities and 50 test entities;
6. independently verify all hashes and counts in Node;
7. preserve the absolute score at 423.

Stage 0 returns `PROCEED` or `STOP`. It cannot award points.

## Frozen baseline family if Stage 0 passes

1. constant vintage rate;
2. CAMELS-lite transparent score;
3. L2 logistic regression;
4. discrete-time survival logistic regression;
5. balanced Random Forest;
6. cost-sensitive Random Forest.

## Frozen challenger family if Stage 0 passes

1. monotonic horizon-weighted gradient boosting;
2. Platt-calibrated Random Forest / monotonic-boosting ensemble;
3. Platt-calibrated survival-logit / Random Forest / monotonic-boosting ensemble.

Calibration and method selection use only a hash-defined validation-calibration subset and a disjoint validation-selection subset. The test is opened once.

## Non-compensable performance gates

A future full result must:

- beat the strongest validation-selected baseline, including Random Forest, by at least 5% relative AUPRC;
- strictly improve recall at 1% FPR;
- not worsen Brier score or calibration error;
- reduce preregistered expected cost by at least 5%;
- improve both 2012 and 2013 when each subset is evaluable;
- have a positive entity-bootstrap lower 95% bound;
- reproduce independently with source, split, prediction, metric and score forgeries rejected.

## Score boundary

A complete independent PASS may add at most 20 absolute points. Stage 0, training, a favorable Python result or a partial gate pass adds zero.

```text
absolute Finance score before Stage 0: 423/1000
```

US$0, official public FDIC data, draft, no merge.