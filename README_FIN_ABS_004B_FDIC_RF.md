# FIN-ABS-004B — untouched FDIC benchmark with Random Forest

## Purpose

FIN-ABS-004 was honestly falsified on 2009–2011: monotonic boosting improved ranking and crisis cost but worsened Brier calibration and lost in the non-crisis year. FIN-ABS-004B uses that result only as development evidence and moves to an **untouched 2012–2014 test period**.

Logic Power remains the meta-controller. It is not part of any bank-risk model.

## Why a new experiment is required

The published U.S. bank-failure literature identifies Random Forest and cost-sensitive forests as strong comparators, while logistic regression remains a strong interpretable baseline. They were not added retroactively to FIN-ABS-004 because its test had already opened.

FIN-ABS-004B therefore freezes the stronger baseline family before acquiring or evaluating the new test.

## Temporal contract

Outcome: FDIC failure strictly after the report date and within 730 days. Assistance transactions remain separate.

- train observations: 1992-12-31 through 2004-12-31; outcomes visible through 2006-12-31;
- validation observations: 2007-03-31 through 2009-12-31; outcomes visible through 2011-12-31;
- untouched test observations: 2012-03-31 through 2014-12-31; outcomes visible through 2016-12-31.

The prior experiment used observations only through 2011. No 2012–2014 model result has been observed.

## Stage 0 power redesign — before any prediction

The original Stage 0 used seed `FIN-ABS-004B-ENTITY-SPLIT-V1` and buckets `20% / 10% / 70%`. It reconstructed `697,255` official bank-quarter rows and proved the untouched test contained signal, but stopped because the entity-disjoint training bucket contained only `22` failed banks versus the preregistered minimum of `30`.

No model, feature importance, threshold, probability or test-performance metric existed. Logic Power therefore selected a pure information-design correction using only aggregate event counts:

- extend the untouched test through 2014;
- replace the seed with `FIN-ABS-004B-ENTITY-SPLIT-V2`;
- train buckets 0–29;
- validation buckets 30–49;
- test buckets 50–99.

The new `30% / 20% / 50%` split increases training and validation power while retaining a large independent test. Assignment still uses only `CERT`, source window, seed and hash; it cannot inspect financial features, labels, predictions or performance.

## Stage 0 gates

Before model construction, CI must reconstruct official rows, construct 730-day labels, separate assistance, prove temporal order, zero duplicates and zero entity overlap, and retain at least `30 / 10 / 50` positive train/validation/test entities. Python and Node must agree. Stage 0 cannot award points.

## Frozen baseline family

- constant vintage rate;
- CAMELS-lite;
- L2 logistic regression and survival logistic regression, raw and Platt-calibrated;
- balanced Random Forest and cost-sensitive Random Forest, raw and Platt-calibrated.

## Frozen challenger family

- monotonic horizon-weighted boosting, raw and Platt-calibrated;
- Platt-calibrated Random Forest / monotonic-boosting ensemble;
- Platt-calibrated survival-logit / Random Forest / monotonic-boosting ensemble.

Validation entities are separated by hash into calibration and selection. Platt calibration uses natural prevalence rather than class weights. Thresholds and method selection use only the selection subset; the test is opened once.

## Non-compensable gates

The challenger must beat the strongest validation-selected baseline, including Random Forest, by at least 5% relative AUPRC; strictly improve recall at 1% FPR; not worsen Brier or calibration; reduce expected cost by at least 5%; improve 2012, 2013 and 2014 separately; pass an entity-bootstrap; and reproduce independently with forgery rejection.

## Score boundary

A complete independent PASS may add at most 20 absolute points. Stage 0, code, training, synthetic tests, a favorable Python result or a partial gate pass adds zero.

```text
absolute Finance score before Stage 0: 423/1000
```

US$0, official public FDIC data, draft, no merge.