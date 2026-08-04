# FIN-ABS-005 — sealed QFBench calibration program

## Purpose

FIN-ABS-005 evaluates quantitative-finance problem solving against the public QFBench harness rather than another internally designed benchmark. QFBench currently contains 87 executable tasks spanning derivatives, risk, credit, market microstructure, factor research, crypto and event-driven finance.

Logic Power selected this route because it offers a direct external comparison against frontier financial agents. Logic Power is the meta-controller only; it is not part of any task solution.

## Frozen source

- repository: `QF-Bench/QuantitativeFinance-Bench`;
- commit: `d2fc28b3492f2d73d192fa7eabadf150a19a62fb`;
- license: CC BY-NC 4.0;
- harness: Harbor task directories with executable verifiers;
- source leaderboard reference: best published pass@1 approximately 61.7% across the complete comparison set.

## Blind calibration subset

The subset was frozen before reading any selected instruction. The candidate IDs came from repository-path discovery only and were ranked by:

`SHA256("FIN-ABS-005-QFBENCH-CALIBRATION-V1" + "|" + task_id)`

The first five are:

1. `structured-note-risk`;
2. `swap-curve-bootstrap-ois`;
3. `double-sort`;
4. `bs-greeks-pde`;
5. `kelly-var-sizing`.

Selection manifest SHA-256:

`ece4ec97f61fa1e0c3422498024207734aaa167b90d5587944b436672da79474`

## Anti-leakage boundary

Stage 0 checks out only:

- `task.toml`;
- `instruction.md`;
- `environment/`;
- root license and execution documentation.

It must prove that no `solution/` or `tests/` file entered the workspace or artifact. Oracle solutions and verifier assertions remain unread. Any accidental acquisition of those paths invalidates the subset permanently.

## Execution protocol

After Stage 0 passes:

1. solve each task from its instruction and supplied environment only;
2. freeze the produced files before invoking the public verifier;
3. run each verifier once for the scored attempt;
4. preserve stdout, reward, output hashes and execution trace;
5. record pass/fail without repairing from hidden-test details;
6. use failures only to improve a future task cohort, never the observed task.

## Score contract

Stage 0 adds zero points. The five-task calibration subset also cannot establish world SOTA because it is small and selected from a discoverable public repository. It may only validate the execution route and estimate whether a larger sealed cohort is worth running.

A later breadth result requires a separate untouched cohort, contamination analysis, at least three independent runs per task, exact cost accounting and direct comparison with the published frontier.

The canonical absolute Finance score remains **423/1000**.
