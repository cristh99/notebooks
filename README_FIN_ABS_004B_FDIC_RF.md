# FIN-ABS-004B — untouched FDIC benchmark with Random Forest

## Purpose

FIN-ABS-004 was honestly falsified on 2009–2011: monotonic boosting improved ranking and crisis cost but worsened Brier calibration and lost in the non-crisis year. FIN-ABS-004B uses that result only as development evidence and moves to an **untouched 2012–2014 test period**.

Logic Power remains the meta-controller. It is not part of any bank-risk model.

## Why a new experiment is required

The published U.S. bank-failure literature identifies Random Forest and cost-sensitive forests as strong comparators, while logistic regression remains a strong interpretable baseline. They were not added retroactively to FIN-ABS-004 because its test had already opened.

## Temporal contract

Outcome: FDIC failure strictly after the report date and within 730 days. Assistance transactions remain separate.

- train observations: 1992-12-31 through 2004-12-31;
- validation observations: 2007-03-31 through 2009-12-31;
- untouched test observations: 2012-03-31 through 2014-12-31.

The prior experiment used observations only through 2011. No 2012–2014 model result has been observed.

## Stage 0 power corrections — all before any prediction

### Version 1 — stopped

Seed `FIN-ABS-004B-ENTITY-SPLIT-V1`, buckets `20% / 10% / 70%`:

- train positive entities: `22`;
- validation: `37`;
- test: `64`.

The train gate required `30`, so the route stopped before model construction.

### Version 2 — stopped

The untouched test was extended through 2014, the seed was changed once to `FIN-ABS-004B-ENTITY-SPLIT-V2`, and buckets were `30% / 20% / 50%`:

- train positive entities: `34`;
- validation: `76`;
- test: `47`.

The test gate required `50`, so the route stopped again before model construction.

### Version 3 — final correction

Without changing seed, dates, source rows or labels, exactly five surplus validation buckets move to test:

- train buckets 0–29;
- validation buckets 30–44;
- test buckets 45–99.

This `30% / 15% / 55%` allocation is the final Stage 0 design. It was selected solely from aggregate event counts; no model, feature importance, threshold, probability or performance existed. If any gate still fails, FIN-ABS-004B stops rather than redesigning again.

## Stage 0 gates

Before model construction, CI must reconstruct official rows, construct 730-day labels, separate assistance, prove temporal order, zero duplicates and zero entity overlap, and retain at least `30 / 10 / 50` positive train/validation/test entities. Python and Node must agree. Stage 0 cannot award points.

## Frozen baseline family if Stage 0 passes

- constant vintage rate;
- CAMELS-lite;
- L2 logistic regression and survival logistic regression, raw and Platt-calibrated;
- balanced Random Forest and cost-sensitive Random Forest, raw and Platt-calibrated.

## Frozen challenger family if Stage 0 passes

- monotonic horizon-weighted gradient boosting, raw and Platt-calibrated;
- Platt-calibrated Random Forest / monotonic-boosting ensemble;
- Platt-calibrated survival-logit / Random Forest / monotonic-boosting ensemble.

Calibration and method selection use a hash-defined validation-calibration subset and a disjoint validation-selection subset. Platt calibration uses natural prevalence rather than class weights. The test is opened once.

## Non-compensable performance gates

A future full result must beat the strongest baseline, including Random Forest, by at least 5% relative AUPRC; strictly improve recall at 1% FPR; not worsen Brier or calibration; reduce expected cost by at least 5%; improve 2012, 2013 and 2014 separately; pass an entity-bootstrap; and reproduce independently with forgery rejection.

## Score boundary

A complete independent PASS may add at most 20 absolute points. Stage 0, training, synthetic tests, a favorable Python result or a partial gate pass adds zero.

```text
absolute Finance score before Stage 0: 423/1000
```

US$0, official public FDIC data, draft, no merge.