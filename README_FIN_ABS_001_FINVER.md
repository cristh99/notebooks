# FIN-ABS-001A — external financial-statement verification slice

## Purpose

This is the first cross-domain external experiment selected after recalibrating broad Finance to **423/1000**. It tests whether the existing rigor and accounting identities transfer to a current public benchmark family instead of adding more internal theory.

The target is **FinVerBench** at commit:

```text
SiluPanda/finverification-bench
8aef2f48befdab5c57cc383a521711fe11c2df98
```

FinVerBench uses SEC 10-K XBRL data and controlled arithmetic, cross-statement, year-over-year and magnitude perturbations.

## Upstream reproducibility audit

The pinned repository's committed `data/processed/*.json` files use a parsed XBRL line-item schema, while its public dataset builder declares a simplified top-level statement schema. FIN-ABS-001A records that mismatch instead of pretending the exact published diagnostic set was reproduced.

A transparent adapter therefore:

1. chooses the latest complete consecutive-year slice per company;
2. preserves reported high-level SEC totals;
3. derives explicit residual buckets needed by the upstream simplified schema;
4. records every residualized field and exclusion;
5. applies the pinned upstream error taxonomy and injection code.

This adapted slice is **not byte-identical to the published 105-row observable subset** and cannot by itself raise the absolute score.

## Candidate policy

`FIN-ABS-001A-CALIBRATED-RELATIONAL-VERIFIER-V1` checks only visible declared relations:

- income-statement arithmetic;
- current and prior balance-sheet identities;
- cash-flow arithmetic;
- net-income, cash, depreciation and retained-earnings links;
- explicit tolerance for rounding;
- fail-closed abstention when too few relationships are observable.

The prediction function never reads benchmark ground truth.

## Predeclared comparisons

Published FinVerBench comparators:

- rule-based baseline: precision `1.000`, recall `0.528`, FPR `0.000`;
- calibrated rounded frontier: recall `0.790`, FPR `0.000`.

Candidate gates:

1. at least 40 adapted companies, 40 clean rows and 50 observable errors;
2. exact precision `1.000`, FPR `0.000`, full coverage;
3. exact recall above `0.528`;
4. rounded FPR `0.000` and recall at least `0.790`;
5. deterministic permutation performs worse;
6. independent Node replay reproduces metrics and gates;
7. score remains `423/1000` because this is an adapted construct-validity slice.

## Reproduce

```bash
git clone https://github.com/SiluPanda/finverification-bench.git upstream
git -C upstream checkout 8aef2f48befdab5c57cc383a521711fe11c2df98

python -m fin_abs_001_finver.adapter \
  upstream/data/processed \
  reports/fin_abs_001_finver/adapted \
  --audit-output reports/fin_abs_001_finver/upstream_schema_audit.json

PYTHONPATH="$PWD/upstream/src:$PWD" \
python -m fin_abs_001_finver.build_benchmark \
  reports/fin_abs_001_finver/adapted \
  reports/fin_abs_001_finver/benchmark \
  upstream/src

python -m fin_abs_001_finver.evaluate \
  reports/fin_abs_001_finver/benchmark/benchmark.json \
  reports/fin_abs_001_finver/benchmark/build_manifest.json \
  reports/fin_abs_001_finver/adapted/adapter_manifest.json \
  reports/fin_abs_001_finver/upstream_schema_audit.json \
  --output-dir reports/fin_abs_001_finver/evaluation
```

## Boundary

The experiment evaluates numerical consistency of visible statements. It does not value companies, predict returns, certify filings as audited, establish fraud, or prove broad Finance SOTA.
