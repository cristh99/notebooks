# FIN-ABS-004B — untouched FDIC benchmark with Random Forest

## Purpose

FIN-ABS-004 was honestly falsified on 2009–2011: monotonic boosting improved ranking and crisis cost but worsened Brier calibration and lost in the non-crisis year. FIN-ABS-004B uses that result only as development evidence and moves to an **untouched 2012–2014 test period**.

Logic Power remains the meta-controller. It is not part of any bank-risk model.

## Strong external baseline requirement

Published U.S. bank-failure research identifies Random Forest and cost-sensitive forests as strong comparators, while logistic regression remains a strong interpretable baseline. They were not added retroactively to FIN-ABS-004 because its test had already opened.

## Frozen temporal contract

- outcome: FDIC failure strictly after the report date and within 730 days;
- assistance transactions remain separate;
- train observations: 1992-12-31 through 2004-12-31;
- validation observations: 2007-03-31 through 2009-12-31;
- untouched test observations: 2012-03-31 through 2014-12-31.

## Stage 0 history — all before prediction

- v1, seed V1, buckets `20/10/70`: positives `22/37/64`; STOP.
- v2, seed V2, buckets `30/20/50`: positives `34/76/47`; STOP.
- v3 final, same seed/data/dates, buckets `30/15/55`: **PASS**.

Final official entity-disjoint cohort:

| Split | Rows | Banks | Positive entities | Positive rows |
|---|---:|---:|---:|---:|
| Train | 164,319 | 4,880 | 34 | 164 |
| Validation | 15,361 | 1,369 | 54 | 322 |
| Test 2012–2014 | 45,693 | 4,032 | 50 | 208 |

- zero entity overlap and zero bank-quarter duplicates;
- panel SHA-256 `31426e433230999f9ce5fca0c08ce0664716e24fee508e584b053e0ecf4bf3da`;
- Stage 0 run `30874478494` — SUCCESS;
- artifact `8879238673`, SHA-256 `60e24c2c418763c817134ff568872a95a43bc0d00fc4376ecd89b174c33de874`;
- Node receipt valid: `0125833ce7716e9f46bc3dd12dd6a4375bdf73723e1233ef31da92ff87fb2764`.

Stage 0 authorizes one sealed evaluation; it awards zero points.

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

A full result must beat the strongest baseline, including Random Forest, by at least 5% relative AUPRC; strictly improve recall at 1% FPR; not worsen Brier or calibration; reduce expected cost by at least 5%; improve 2012, 2013 and 2014 separately; pass an entity-bootstrap; and reproduce independently with source, split, metric, year-gate and score forgeries rejected.

## Score boundary

Stage 0, code, synthetic tests, model fitting, a favorable Python result or partial gates add zero. A complete independent PASS may add at most 20 absolute points.

```text
absolute Finance score before sealed execution: 423/1000
```

US$0, official FDIC data, draft, no merge.