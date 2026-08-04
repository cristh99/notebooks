# FIN-ABS-004B — untouched FDIC benchmark with Random Forest

## Purpose

FIN-ABS-004 was honestly falsified on 2009–2011: monotonic boosting improved ranking and crisis cost but worsened Brier calibration and lost in the non-crisis year. FIN-ABS-004B uses that result only as development evidence and moves to an **untouched 2012–2014 test period**.

Logic Power remains the meta-controller. It is not part of any bank-risk model.

## Why a new experiment is required

Published U.S. bank-failure research identifies Random Forest and cost-sensitive forests as strong comparators, while logistic regression remains a strong interpretable baseline. They were not added retroactively to FIN-ABS-004 because its test had already opened.

## Frozen temporal contract

- outcome: FDIC failure strictly after the report date and within 730 days;
- assistance transactions remain separate;
- train observations: 1992-12-31 through 2004-12-31;
- validation observations: 2007-03-31 through 2009-12-31;
- untouched test observations: 2012-03-31 through 2014-12-31.

No 2012–2014 model result has been observed.

## Stage 0 power audit — before any prediction

### v1 — stopped

Seed `FIN-ABS-004B-ENTITY-SPLIT-V1`, buckets `20% / 10% / 70%` produced positive entities `22 / 37 / 64`; train failed the minimum 30.

### v2 — stopped

The test was extended through 2014, seed changed once to `FIN-ABS-004B-ENTITY-SPLIT-V2`, and buckets `30% / 20% / 50%` produced `34 / 76 / 47`; test failed the minimum 50.

### v3 — final design

Without changing seed, dates, source rows or labels, five surplus validation buckets move to test:

- train buckets 0–29;
- validation buckets 30–44;
- test buckets 45–99;
- minima `30 / 10 / 50` positive entities.

Every redesign used only aggregate event counts. No model, feature importance, threshold, probability or performance existed. If v3 fails, the route stops.

## Frozen baseline family

- constant vintage rate;
- CAMELS-lite;
- L2 logit and survival logit, raw and Platt-calibrated;
- balanced Random Forest and cost-sensitive Random Forest, raw and Platt-calibrated.

## Frozen challenger family

- monotonic horizon-weighted boosting, raw and Platt-calibrated;
- Platt-calibrated Random Forest / monotonic-boosting ensemble;
- Platt-calibrated survival-logit / Random Forest / monotonic-boosting ensemble.

Validation entities are separated by hash into calibration and selection. Platt calibration uses natural prevalence without class weights. Thresholds and method selection use only the selection subset. The test opens once.

## Non-compensable gates

A full result must beat the strongest baseline, including Random Forest, by at least 5% relative AUPRC; strictly improve recall at 1% FPR; not worsen Brier or calibration; reduce expected cost by at least 5%; improve 2012, 2013 and 2014 separately; pass an entity-bootstrap; and reproduce independently with forgery rejection.

## Score boundary

Stage 0, code, synthetic tests, model fitting, a favorable Python result or partial gates add zero. A complete independent PASS may add at most 20 absolute points.

```text
absolute Finance score: 423/1000
```

US$0, official FDIC data, draft, no merge.