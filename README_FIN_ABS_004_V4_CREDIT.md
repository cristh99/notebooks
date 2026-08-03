# FIN-ABS-004 — V4FinBench credit-risk program

## Purpose

Test an unobserved Finance domain: public corporate distress prediction under severe class imbalance and company-level separation.

Logic Power selects a two-stage fail-closed route:

1. **Public-data audit** — acquire the canonical Kaggle release anonymously, identify its immutable dataset version, hash all seven parquet files, and verify scale, schema, label prevalence, company grouping, country coverage, and year coverage.
2. **Sealed credit benchmark** — only after the audit passes, freeze one horizon and one released fold; compare strong tree baselines against a calibrated challenger under discrimination, rare-event precision, calibration, selective-decision utility, and independent replay gates.

## Frozen sources

- Dataset: `sebastiantomczak10/v4-group-corporate-bankruptcy`
- Upstream code: `leokeechye/V4FinBench`
- Upstream commit: `908b88d373a76e0064329e38fc01cba98bebae5f`
- Primary future task: `company_years_h2.parquet`, corresponding to the benchmark's one-year-ahead horizon.

## Data-audit gates

The audit passes only if all are true:

- the seven expected parquet files are present, and only those seven are evaluated;
- the primary task has at least 500,000 rows and 130 columns;
- at least 125 feature columns remain after excluding label, company, country, and year;
- the target exists, contains at least 1,000 positive events, and has no nulls;
- company, country, and year keys exist;
- at least 100,000 companies, four countries, and ten years are represented;
- every file has a valid SHA-256 digest;
- no raw dataset rows are embedded in the report artifact.

Anonymous-download failure returns `BLOCKED_DATA_ACCESS`, not a fabricated empty dataset. Schema or scale failure returns `BLOCKED_DATA_AUDIT`.

## Score boundary

The audit cannot increase the absolute Finance score. It remains **423/1000** until a separately preregistered predictive benchmark passes external-performance, calibration, economic-utility, and replay gates.

## Reproduction

```bash
python -m unittest -v fin_abs_004_v4_credit.test_audit
python -m fin_abs_004_v4_credit.audit --output-dir reports/fin_abs_004_v4_credit_audit
node fin_abs_004_v4_credit/verify_audit.mjs \
  reports/fin_abs_004_v4_credit_audit/audit.json \
  reports/fin_abs_004_v4_credit_audit/node_receipt.json
```

The GitHub workflow pins `kagglehub==1.0.2`, `pyarrow==25.0.0`, and Python 3.12, records runtime versions, publishes only the audit report and hashes, and rejects rehashed score or status forgeries.
