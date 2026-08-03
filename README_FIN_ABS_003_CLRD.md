# FIN-ABS-003 — external insurance loss-reserving benchmark

## Purpose

FIN-ABS-003 tests whether a deterministic, credibility-weighted reserving method improves real insurer reserve forecasts across lines of business without sacrificing calibration or tail safety. Logic Power selected this domain after the SEC breadth route was externally blocked and the PortBench portfolio challenger was falsified on its sealed test.

Logic Power is only the meta-controller. It is not part of the reserving model.

## Frozen external source

- Dataset: CAS Loss Reserving Database (`clrd.csv`).
- Public implementation repository: `casact/chainladder-python`.
- Source commit: `2f6ea125d17e29d018b56e4df85eda52ac8ac206` (`chainladder` v0.9.2).
- Source path: `chainladder/utils/data/clrd.csv`.
- Git blob: `04e54cfa41e7bd879877e5c5aea5e63a6d20d29b`.
- Expected structure: 775 insurer/line triangles, six lines of business, ten accident years and ten development lags.

The CI audit computes and freezes the transport SHA-256 before any forecasting result is produced.

## Forecasting problem

For each insurer/line triangle, create retrospective valuation dates at year-end 1994, 1995 and 1996. At each cutoff:

1. reveal only cells whose `DevelopmentYear <= cutoff`;
2. forecast each eligible accident year's cumulative paid loss at year-end 1997;
3. define the required reserve as `CumPaidLoss_1997 - CumPaidLoss_cutoff`;
4. compare predicted reserve against the actually observed 1997 amount.

Cases with missing identifiers, nonpositive current cumulative paid, missing target, target below current, or nonpositive earned premium are excluded by a fixed data-quality rule and counted explicitly.

## Entity-disjoint split

All lines belonging to the same `GRCODE` remain in one split. Split assignment is frozen before outcomes are examined:

```text
bucket = first_8_bytes(SHA256("GRCODE|FIN-ABS-003-SPLIT-V1")) mod 100
train      = 00–59
validation = 60–79
test       = 80–99
```

Training entities estimate pooled development and expected-loss parameters. Validation entities choose among the finite preregistered challenger variants. Test entities are opened once.

## Strong baselines

Every method uses the same cases and information cutoff:

1. `COMPANY_CHAIN_LADDER` — volume-weighted development factors from the insurer's own visible triangle;
2. `LOB_POOLED_CHAIN_LADDER` — volume-weighted factors from training insurers in the same line;
3. `BORN_HUETTER_FERGUSON` — pooled expected target loss ratio and pooled percent developed;
4. `CAPE_COD` — cutoff-specific expected loss ratio inferred from visible paid and exposure;
5. `VALIDATION_BEST_BASELINE` — the lowest validation WAPE among the four methods, selected before test.

## Challenger family

Only these variants may compete on validation data:

- `ROBUST_CRED_25`;
- `ROBUST_CRED_50`;
- `ROBUST_CRED_75`.

For each development lag, the challenger:

1. computes insurer-specific and training-pool link ratios;
2. winsorizes training-company ratios at median ± 3 MAD;
3. blends insurer and robust pooled factors using volume credibility;
4. generates a chain-ladder reserve forecast;
5. blends that forecast with the Bornhuetter–Ferguson forecast using the fixed weight 25%, 50% or 75% on the robust chain-ladder component.

The single validation winner is selected by lowest WAPE, breaking ties by lower aggregate calibration error, lower 95th-percentile absolute percentage error, and method name. No variant or threshold changes after test disclosure.

## Primary metrics

- weighted absolute percentage error: `sum(abs(predicted−actual)) / sum(actual reserve)`;
- aggregate calibration ratio: `sum(predicted) / sum(actual)`;
- aggregate calibration error: `abs(ratio−1)`;
- median and 95th-percentile absolute percentage error;
- under-reserving frequency and aggregate under-reserve amount;
- line-of-business WAPE;
- cutoff-year WAPE;
- paired entity-level WAPE improvement;
- cluster moving-block/bootstrap confidence interval over insurer entities.

## Non-compensable gates

All gates must pass:

1. source commit and audited dataset SHA are exact;
2. at least 500 insurer/line triangles and all six lines survive audit;
3. at least 5,000 eligible retrospective forecast cases;
4. entity-disjoint split with zero `GRCODE` leakage;
5. zero temporal leakage: no factor or loss ratio uses a cell after the valuation cutoff, and no test entity contributes to pooled parameters;
6. challenger test WAPE is at least 2% relatively lower than the validation-selected strongest baseline;
7. challenger aggregate calibration error is no worse than baseline by more than 1 percentage point;
8. challenger 95th-percentile APE is no worse than baseline by more than 5 percentage points;
9. challenger improves WAPE in at least four of six lines of business;
10. lower 95% entity-bootstrap bound for paired WAPE improvement is positive;
11. Python and an independent Node implementation reproduce the selected method, predictions, metrics, split, hashes and score;
12. source, split, prediction, metric and score forgeries are rejected.

## Absolute score contract

A full PASS may add at most:

- world-SOTA superiority: `+5`;
- historical originality: `+0`;
- cross-domain generality: `+6`;
- external validation and impact readiness: `+7`;
- rigor and reproducibility: `+2`;
- autonomous growth: `+0`.

Maximum delta: **+20 absolute points**. No points are awarded for the data audit alone, and this experiment cannot declare universal Finance SOTA.

## Falsification

The challenger is falsified on this benchmark if any non-compensable gate fails, the strongest baseline wins, calibration or tail error breaches its tolerance, improvement is concentrated in fewer than four lines, or an independent implementation disagrees.

## Boundary

A PASS would establish a bounded retrospective reserving result on U.S. Schedule P data. It would not certify an insurer's booked reserve, future solvency, regulatory capital, claims adequacy, live deployment, global transfer, or historical priority.
