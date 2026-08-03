# FIN-ABS-002 — external multi-asset portfolio benchmark

## Purpose

FIN-ABS-002 attacks the largest remaining absolute Finance deficits: world-SOTA superiority, external validation, cross-domain generality, and real decision quality. Logic Power is used only as the meta-controller that selected this experiment; it is not embedded in the portfolio model.

## Frozen external source

- Benchmark: **PortBench**, `AgenticFinLab/portbench`.
- Source commit: `5e7cce2e1214a5dd026578c8814953f358b5a475`.
- Market dataset: `AgenticFinLab/PortBench-Market`, file `market-base-dataset.csv`.
- Dataset SHA-256 declared by the repository: `495659fb40690d48748dcbcbd8c8c2add5371fac9d5be535270959ae8f519221`.
- Coverage: 2015-01-02 through 2025-12-31, 183 instruments, six asset classes.
- Split contract from the pinned preprocessing specification: train 2015–2022, validation 2023, sealed test 2024–2025. The run fails if the dataset's own labels do not agree.

The benchmark is read-only and public. No model API, cloud VM, GCloud, MotherDuck, OCR, crawler, or paid data is required.

## Problem

Determine whether a deterministic, cost-aware and correlation-aware portfolio policy can beat the strongest classical PortBench baselines on the sealed 2024–2025 test period without sacrificing stress survival.

## Baselines

Every strategy uses the same prices, rebalance dates, costs, eligibility rules, and metrics:

1. equal weight;
2. 60/40 with alternatives disabled;
3. inverse-volatility risk parity;
4. full-covariance equal-risk-contribution;
5. long-only minimum variance;
6. Black–Litterman when the frozen PortBench implementation is callable at the pinned commit.

The best validation baseline becomes the primary comparator before the sealed test is opened.

## Challenger family

Only the following three variants may be compared on validation data:

- `ROBUST_ERC`: 50% diagonal covariance shrinkage, equal-risk-contribution, 35% asset-class cap and 10% single-asset cap;
- `ROBUST_ERC_NTB`: `ROBUST_ERC` plus a 10% L1 no-trade band and 50% partial adjustment toward a changed target;
- `ROBUST_SURVIVAL`: `ROBUST_ERC_NTB` plus a fixed 25% shift to cash when trailing 60-day portfolio drawdown is at or below −8% or trailing 60-day annualized volatility exceeds 25%.

The single validation winner is selected by net Sharpe, breaking ties by lower drawdown, lower Expected Shortfall and then lower turnover. No threshold or model change is allowed after the sealed result is observed.

## Temporal and execution contract

- monthly decisions at the first available trading date of each month;
- all estimators use dates strictly earlier than the decision date;
- minimum 252-day trailing window, maximum 756 days;
- no shorting and weights sum to one;
- 15 bps linear trading cost per unit of one-way turnover, matching PortBench's published execution convention;
- missing or stale assets receive zero new weight;
- cash remains an admissible asset;
- no use of future returns, full-sample covariance, or test-period parameter tuning.

## Primary metrics

- net annualized return and Sharpe ratio;
- maximum drawdown;
- Expected Shortfall at 95%;
- turnover and total trading cost;
- stress-window survival;
- class concentration and maximum single-asset weight;
- paired monthly net-return difference against the selected strong baseline;
- moving-block-bootstrap confidence interval for the paired difference.

## Non-compensable gates

All gates must pass:

1. exact dataset SHA-256 and pinned source commit;
2. exact declared split labels and zero point-in-time violations;
3. identical execution and cost layer for every strategy;
4. sealed validation selection and one-shot 2024–2025 test;
5. challenger net Sharpe exceeds the best validation-selected baseline on the sealed test;
6. challenger maximum drawdown is no worse than the comparator by more than 100 bps;
7. challenger Expected Shortfall is no worse than the comparator by more than 100 bps;
8. lower 95% moving-block-bootstrap bound for paired monthly net-return improvement is positive;
9. all PortBench profile/stress safety gates applicable to the frozen universe pass;
10. Python and Node independently reproduce weights, returns, costs, metrics, selected strategy, and score;
11. score, weights, dataset, split, and receipt forgeries are rejected.

## Absolute score contract

A full PASS may add at most:

- world-SOTA superiority: `+12`;
- cross-domain generality: `+6`;
- external validation and impact readiness: `+8`;
- rigor/reproducibility: `+2`;
- historical originality: `+0`;
- autonomous growth: `+0`.

Maximum delta: **+28 absolute points**. The experiment cannot declare Finance 1000/1000 and cannot claim a new general theory of portfolio choice.

## Falsification

The challenger is falsified for this benchmark if any non-compensable gate fails, the best classical baseline wins after costs, the improvement vanishes under the sealed test, or risk deteriorates beyond the declared tolerance.

## Boundary

A PASS would establish a bounded external portfolio-management result on PortBench's published data and execution contract. It would not prove live tradability, broker-grade market impact, tax efficiency, capacity at institutional scale, universal asset-pricing superiority, fiduciary suitability, or historical priority.
