# FIN-ABS-001B — SEC direct-fact breadth benchmark

## Purpose

The absolute Finance score is **423/1000**. FIN-ABS-001B is the next
Logic-Power-selected separating experiment: test whether the accounting
verification capability transfers from an adapted 17-company slice to a
broad, direct, official SEC cohort without residualizing or inventing any
financial line item.

## Frozen design

The protocol is committed before the remote result is observed.

- Universe: the 50 companies in the public FinVerBench acquisition script.
- Source: `data.sec.gov/api/xbrl/companyfacts` only.
- Filing boundary: one 10-K or 10-K/A accession per company.
- Values: directly reported USD XBRL facts only.
- No imputation, residual bucket, sector equivalence, synthetic statement
  field, or post-result threshold change.
- Candidate relations are screened for source consistency before controlled
  perturbation; every rejected source relation remains in the evidence log.
- Exact and rounded-to-millions variants use the same frozen verifier.
- Python generates decisions; Node independently reimplements decisions,
  metrics, permutation control, gates, provenance checks, and score logic.

## Relations

1. Assets = liabilities and stockholders' equity total.
2. Assets = liabilities + equity.
3. Gross profit = revenue − cost of revenue.
4. Net cash change = CFO + CFI + CFF + exchange effect.
5. Ending cash = prior cash + net cash change, only when the cash concepts are
   semantically identical across periods.

## Gates

All must pass:

- at least 40 eligible companies;
- at least 25 companies with two or more direct relations;
- at least 80 direct relations;
- at least 20 distinct SIC codes;
- every value has direct SEC accession/concept provenance;
- exact precision 100%, FPR 0, recall at least 90%, coverage 100%;
- rounded FPR 0 and recall at least 85%;
- fixed permutation control is worse;
- Node replay agrees;
- score and prediction forgeries are rejected.

## Score contract

A complete pass may move the absolute score only:

- generality: +4;
- external validation: +4;
- world-SOTA: +0;
- historical originality: +0.

Therefore the maximum result of this experiment is **431/1000**, not 1000.

## Boundary

This experiment verifies selected numerical relationships in official filings.
It does not value companies, forecast returns, certify audited statements,
detect fraud, or establish general Finance SOTA.

## Cost and isolation

- Paid infrastructure: **US$0**.
- No GCloud, MotherDuck, OCR, crawler, or other-agent process is touched.
- Branch remains isolated, draft, and unmerged.
