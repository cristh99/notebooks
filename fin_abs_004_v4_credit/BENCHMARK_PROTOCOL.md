# FIN-ABS-004 — frozen credit-calibration benchmark

## Question

Does a calibration-and-ensemble layer improve probability reliability for one-year-ahead corporate distress without sacrificing discrimination or high-capacity screening performance?

## Data

- Dataset: `sebastiantomczak10/v4-group-corporate-bankruptcy`, version `6`.
- File: `company_years_h2.parquet`.
- Frozen SHA-256: `e9fa1b9cb51ea03f3f2582d08674d7b5039e32fb049363f8f2aa12e4dfc76eeb`.
- Rows: 996,500; positive labels: 3,054.
- Label: upstream composite financial-distress target, not a legal-bankruptcy-only label.

## Splits

The upstream company-grouped, country-stratified five-fold rule is reproduced with seed 42. For fold `i`:

- validation = fold `i`;
- test = fold `(i + 1) mod 5`;
- training = remaining three folds.

No company may cross train, validation, or test. Validation companies are deterministically divided in half: calibration and model-selection/threshold selection. Test labels never influence model choice, calibration, weighting, or thresholds.

## Fixed models

- XGBoost: 200 trees, depth 5, learning rate 0.05.
- LightGBM: 200 trees, 31 leaves, learning rate 0.05.
- Challenger: Platt-calibrate both fixed models on the calibration half, then select one convex weight from `{0, .25, .5, .75, 1}` on the selection half by Brier score.
- Baseline: whichever uncalibrated tree model has higher selection average precision; ties resolve by lower selection Brier.

No parameter is changed after test outcomes are observed.

## Gates

All must pass:

1. exact dataset version and file hash;
2. five complete folds and zero company overlap;
3. at least 400 positive events in each test fold;
4. baseline ROC-AUC ≥ 0.75 and average precision ≥ 0.03;
5. challenger Brier relative gain ≥ 2%;
6. challenger log-loss relative gain ≥ 1%;
7. challenger ECE relative gain ≥ 10%;
8. ROC-AUC and average precision non-inferior within 0.001;
9. F1 non-inferior within 0.005;
10. top-0.5%-capacity precision and recall non-inferior within 0.005;
11. Brier and ECE improve in at least four of five folds;
12. late-three-year Brier improves and average precision remains within 0.002;
13. company-clustered Brier-gain 95% interval remains above zero;
14. Brier improves in at least three countries and no country loses more than 0.0005;
15. a fixed permutation degrades average precision and Brier;
16. independent Node replay validates the report, verification sample, terminal state, and score.

## Score contract

A complete pass moves the absolute score only from `423` to `429`:

- +4 external validation;
- +2 cross-domain generality;
- +0 world-SOTA superiority;
- +0 historical originality.

Any failed gate leaves the score at `423` and labels the candidate `FALSIFIED_CREDIT_CALIBRATION`.

## Scope

The result is limited to calibration and selective reliability on this benchmark's one-year-ahead composite distress target. It is not causal bankruptcy theory, a legal default determination, a lending recommendation, or universal credit SOTA.
