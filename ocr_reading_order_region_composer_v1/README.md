# OCR Reading Order Region Composer v1

This is the minimum experiment selected by Logic Power Problem Solver v1 after the page-level contextual router failed promotion on PR #34.

Logic Power and the Problem Solver remain development-time controllers. They are not imported by OCR runtime.

## Core idea

Whole-page switching was too coarse: it either protected a header and missed useful body columns, or reordered the entire page and damaged metadata. The region composer instead freezes three vertical bands:

```text
top 0–30%       → row-major baseline
middle 30–65%   → wide-anchor spanning-column order
lower 65–100%   → independently applied wide-anchor spanning-column order
```

A block wider than 70% of the page acts as a separator inside the middle or lower region. Inputs are block boxes and page dimensions only.

## Development boundary

The two previously opened Honduran holdouts—20 pages from 10 processes—are now **development data only**. They cannot support a promotion claim. The replay:

- binds the exact preparation artifacts and annotations from PRs #33 and #34;
- evaluates baseline plus 12 fixed band candidates;
- requires perfect weighted constraint accuracy and perfect partial-order pages before minimizing canonical edit;
- breaks exact ties by protecting more header area, then using a later lower split;
- runs leave-one-process-out diagnostics;
- freezes a candidate only for a future independent holdout.

## Candidate family

Header fractions:

```text
0.25, 0.30, 0.35, 0.40
```

Lower splits:

```text
0.55, 0.65, 0.75
```

Wide-anchor ratio is fixed at `0.70`.

The expected full-development selection is `band_30_65`. This expectation is committed before public CI and is not a holdout claim.

## Freeze gate

The candidate may proceed to a new holdout only when all are true:

- selected candidate is `band_30_65`;
- all development constraints are correct;
- every development page satisfies its partial order;
- mean canonical edit improves by at least 50% versus baseline;
- zero development pages are harmed;
- at least five pages improve;
- full-selection stability occurs in at least 8/10 process-blocked folds.

Even a PASS only means `FREEZE_FOR_NEW_HOLDOUT`; it never means production deployment.

## Constraints

- external spend: `$0`;
- GCloud: forbidden and unused;
- paid APIs: unused;
- GPU: unused;
- no OCR rerun or image download;
- exact artifact hashes and independent semantic replay;
- draft and unmerged until evidence closes.
