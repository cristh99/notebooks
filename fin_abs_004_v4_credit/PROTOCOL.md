# Frozen protocol

This stage audits public access and data integrity only. It cannot change the absolute Finance score.

- Dataset: `sebastiantomczak10/v4-group-corporate-bankruptcy`
- Upstream code: `leokeechye/V4FinBench@908b88d373a76e0064329e38fc01cba98bebae5f`
- Future task: `company_years_h2.parquet`, the benchmark's one-year-ahead corporate-distress horizon.
- Required scale: at least 500,000 rows, 130 columns, 125 feature columns, 1,000 positive labels, 100,000 companies, four countries, and ten years.
- Labels must contain no nulls. All seven expected parquet files must be present and hashed.
- Anonymous access failure is `BLOCKED_DATA_ACCESS`; schema failure is `BLOCKED_DATA_AUDIT`.
- Score remains `423/1000` until a separate sealed predictive benchmark passes.
