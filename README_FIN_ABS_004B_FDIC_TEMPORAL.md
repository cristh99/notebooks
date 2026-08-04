# FIN-ABS-004B — FDIC temporal bank-distress benchmark

## Why this protocol exists

FIN-ABS-004 reconstructed 630,365 official FDIC bank-quarter observations but correctly blocked before opening the sealed test: a globally entity-disjoint split left only seven positive validation rows. Two outcome-blind ownership rules produced the same insufficiency. The blocked design and its evidence remain immutable.

FIN-ABS-004B asks a different, deployment-faithful question:

> Given all public information available at a quarter-end, can a model identify banks that will fail within eight quarters better than strong off-site monitoring baselines in later, unseen calendar regimes?

A bank may appear in more than one period because supervisors repeatedly score existing institutions. This protocol tests **future-time generalization**, not unseen-bank generalization. Entity recurrence is measured explicitly and uncertainty is clustered by bank.

Logic Power is only the meta-controller that selected this redesign after the stronger entity-disjoint hypothesis proved statistically unevaluable. It is not part of the model.

## Frozen source and panel

- official FDIC BankFind financial and failure endpoints;
- 161 live financial fields and 33 failure fields verified before modeling;
- 4,115 historical failure/assistance records;
- 72 quarter-end acquisitions covering the declared windows and lookbacks;
- observation: `CERT × REPDTE`;
- outcome: FDIC `FAILURE` within 730 days; `ASSISTANCE` is excluded from the positive label;
- all feature windows are trailing and use dates strictly before or at the forecast date.

## Temporal windows

- train: `1992-12-31` through `2002-12-31`;
- gap for complete eight-quarter outcomes;
- validation: `2005-03-31` through `2006-12-31`;
- gap for complete eight-quarter outcomes;
- sealed test: `2009-03-31` through `2011-12-31`;
- outcomes observable through `2013-12-30`.

The test remains unopened until the temporal preflight passes.

## Baselines and challengers

Baselines:

1. training-vintage constant rate;
2. transparent CAMELS-lite score;
3. L2 logistic regression;
4. horizon-weighted survival logistic regression.

Challengers:

1. monotonic histogram gradient boosting;
2. horizon-weighted monotonic boosting;
3. calibrated survival-logit/boosting ensemble.

Model family, features, monotonic directions, missingness policy, class weights, calibration, false-negative cost (`100`) and false-positive cost (`1`) are frozen before test.

## Non-compensable temporal preflight

Before the test can run, CI must verify:

- panel hash matches the acquisition report;
- only declared splits exist;
- zero duplicate `CERT × REPDTE` rows;
- strict calendar order and two-year outcome gaps;
- at least 20 positive validation rows and 100 positive test rows;
- all positive labels have a strictly future failure date within 730 days;
- repeated entities are quantified rather than hidden;
- source, panel, split and preflight receipts are hash-bound.

## Performance gates

The validation-selected challenger must, on the sealed test:

- exceed the strongest selected baseline's AUPRC by at least 5% relatively;
- have strictly higher recall at 1% FPR;
- have no worse Brier score or calibration error;
- reduce preregistered expected screening cost by at least 5%;
- preserve improvement under a bank-cluster bootstrap;
- pass crisis and non-crisis cost checks when each subset has enough positive events;
- reproduce metrics and method selection independently in Node;
- reject source, split, metric and score forgeries.

## Score boundary

A performance candidate PASS awards **zero points immediately**. A separate implementation must reconstruct labels, preprocessing, models, probabilities and gates before any promotion.

After that independent replay, this temporal result may add at most:

- world-SOTA superiority: `+3`;
- cross-domain generality: `+3`;
- external validation and impact readiness: `+4`;
- rigor and reproducibility: `+2`;
- historical originality: `+0`;
- autonomous growth: `+0`.

Maximum eventual delta: **+12**. It cannot establish unseen-bank generalization, regulatory fitness, solvency, misconduct, fraud or universal Finance SOTA.

## Isolation

This is a new branch and workflow. FIN-ABS-004 remains preserved as the falsifiable entity-disjoint attempt. US$0, public data, draft, no merge.
