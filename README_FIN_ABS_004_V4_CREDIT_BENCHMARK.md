# FIN-ABS-004 — sealed V4FinBench credit calibration experiment

The data audit passed on dataset version 6. This branch now executes the separately frozen predictive stage.

- 996,500 rows, 3,054 positive one-year-ahead composite distress events.
- Five company-disjoint, country-stratified folds.
- Fixed XGBoost and LightGBM baselines.
- Challenger limited to Platt calibration and a five-point convex weight grid.
- Calibration and selection use disjoint halves of the validation companies.
- Test outcomes cannot alter preprocessing, parameters, weights, thresholds, gates, or score policy.
- Full pass can raise Finance only from 423 to 429; any failed gate leaves 423.

See `fin_abs_004_v4_credit/BENCHMARK_PROTOCOL.md` for exact gates and scope.
