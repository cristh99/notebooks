---
name: motherduck-ops-governor
description: Use before creating, scheduling, running, repairing, slowing, retiring, or replacing MotherDuck Flights and before adding persistent MotherDuck analytics, so the next operation is the lowest-risk action that changes a live decision without disturbing active work.
---

# MotherDuck Operations Governor

## Trigger

Activate before any nontrivial MotherDuck operational decision involving Flights, schedules, Dives, persistent tables, shares, or recurring monitoring. It is especially relevant when the workspace contains many agents, repeated `NOOP` runs, overlapping schedules, completed external jobs, unexplained failures, or pressure to create another pipeline.

Do not activate for a read-only query whose answer is already determined and which cannot affect operational state.

## Core principle

Do not optimize activity. Optimize:

```text
new verifiable decision value / (cost × time × operational risk)
```

A run, Flight, table, chart, or monitor has zero operational value when no possible result can change the current decision.

## Authority boundary

This skill is a read-only governor. It selects, rejects, or specifies work. It does not silently mutate MotherDuck, cancel a worker, spend money, delete evidence, or change an active agent's lease. Any external write requires a separate authorization-bearing executor.

Schema changes and Dive persistence are also external writes: prepare an idempotent migration or reviewed Dive source plus rollback first, then obtain a separate explicit confirmation before calling `query_rw` or `save_dive`.

MotherDuck is an analytical and orchestration layer. GCS retains primary bytes and hashes, BigQuery retains exhaustive canonical facts, GitHub retains code and tests, and Notion retains decisions and semantic guidance.

## Inputs

- The decision to be made and its terminal property.
- Current Flight inventory, schedules, versions, recent runs, and log fingerprints.
- Active external jobs, controllers, shards, checkpoints, watermarks, and leases.
- Expected observations under each serious operational hypothesis.
- Run duration distribution, schedule interval, query bytes, storage, and cost limits.
- Canonical output location, provenance requirements, permissions, reversibility, and stopping rule.

## Operational hypotheses

At minimum consider:

- `LEASED_ACTIVE`: the process is producing material delta or controls active external work.
- `NOOP_STABLE`: inputs and canonical outputs are unchanged.
- `TERMINAL_STALE`: the monitored job or bounded wave is complete and stable.
- `FAILED_DETERMINISTIC`: the same non-transient error repeats without possible progress.
- `SUPERSEDED`: a newer canonical path already performs the function.
- `OVERLAPPING`: schedule frequency is shorter than safe runtime and runs overlap.
- `UNDERSPECIFIED`: available evidence does not identify which state applies.

Remove hypotheses contradicted by current evidence. Preserve competing explanations until a separating observation is obtained.

## Procedure

1. **Type the terminal.** The recommendation must end as `KEEP_ACTIVE`, `NO_CHANGE`, `BACKOFF`, `RETIRE_SCHEDULE`, `REPAIR_ISOLATED`, `ON_DEMAND_ONLY`, `BUILD_ANALYTIC_ASSET`, or `BLOCKED`, followed by a standard skill terminal.
2. **Inventory read-only state.** Read guides first, then list definitions, schedules, versions, recent runs, logs, database objects, Dives, and active external resources. Never infer liveness from the word `ACTIVE` on a definition alone.
3. **Protect leases.** Treat work as leased when any of these hold:
   - it was created or materially updated during the last six hours;
   - a run is pending or executing;
   - it controls an external job that is pending or running;
   - checkpoints, manifests, rows, or a watermark are changing;
   - another agent has declared the front active.
4. **Generate serious alternatives.** Do not assume success means useful work or failure means harmless waste. Distinguish material progress, cheap preflight `NOOP`, repeated heavy `NOOP`, terminal monitoring, deterministic failure, and supersession.
5. **Choose the minimum separating observation.** Prefer, in order:
   - current run state and external job state;
   - two time-separated watermark or fingerprint observations;
   - repeated log-status fingerprint;
   - p95 runtime versus schedule interval;
   - exact output and responsibility overlap with a successor.
   Do not launch a new Flight merely to diagnose an existing Flight when system metadata or logs can decide the question.
6. **Filter inadmissible operations.** Reject actions that are unauthorized, irreversible without consent, outside budget, capable of deleting the only receipt, or likely to disturb a live lease.
7. **Select the lowest-risk decision-changing operation.** Apply these defaults:
   - material delta or active external job → `KEEP_ACTIVE`;
   - three identical cheap `NOOP` observations → increase interval at least threefold;
   - twelve identical `NOOP` observations → `RETIRE_SCHEDULE` or event/on-demand execution;
   - three identical deterministic failures → retire schedule before isolated repair;
   - completed external job plus two stable observations → retire its dedicated monitor;
   - one-shot, diagnostic, profile, inspect, verify, repair, probe, audit, or canary → no recurring schedule unless a documented exception exists;
   - overlapping runs → require mutual exclusion and interval `max(5 minutes, 2 × recent p95 runtime)`;
   - superseded definition → disable schedule, preserve history, and point to successor;
   - repeated human or agent questions over existing state → build a view or Dive rather than another polling pipeline.
8. **Preserve provenance automatically.** Record definition/version, input fingerprint, output locator, code or query identity, run number, cost, terminal, error fingerprint, and before/after state. Preserve the only receipt even when retiring a schedule.
9. **Verify counterfactually.** State which future observation would reverse the recommendation. Compare the post-action state with the pre-action snapshot. No change is successful only when it prevents waste without reducing material output.
10. **Integrate knowledge.** Publish reusable rules and verified repairs to the MotherDuck guide and Notion. Keep transient logs out of the Knowledge Base.

## Decision packet

Return:

- typed operational question;
- compatible hypotheses;
- active leases;
- minimum separating observation and result;
- rejected operations with reasons;
- selected operation and successor, if any;
- expected reduction in activations, compute, or risk;
- provenance and rollback locations;
- counterfactual reversal condition;
- standard terminal and deterministic digest.

## Standard terminals

- `PASS`: the selected recommendation is supported and respects all leases and invariants.
- `UNKNOWN`: another admissible observation is required.
- `IMPOSSIBLE`: opposite recommendations cannot be distinguished with available metadata and permitted observations.
- `INCONSISTENT`: inventory, runs, outputs, or declared authority conflict.
- `REJECTED`: the proposed operation lacks authority, safety, provenance, or budget.

## Safety invariants

- No deletion by default.
- No cancellation before the recurring trigger is stopped, except for an immediate safety emergency.
- No mutation of a Flight created or updated by another active agent without a fail-closed defect and a reversible plan.
- No promotion from a candidate signal to a factual, legal, or financial conclusion.
- No new schedule without idempotence, mutual exclusion, bounded cost, a stopping rule, and a verifiable receipt.
- No `query_rw` call without a separately stated schema/data diff, rollback, and explicit confirmation.
- No `save_dive` call until the design has been reviewed and the user explicitly confirms that iteration is complete.
- No secret in source, config, logs, Dives, or URL state.
- No claim that a `NOOP` is material progress.

## Evaluation

Evaluate first in read-only shadow mode on frozen Flight histories. Include fixtures for:

- active progress that must not be disturbed;
- a terminal monitor;
- a recurring one-shot task;
- repeated cheap and heavy `NOOP` runs;
- repeated deterministic failure;
- overlapping long runs;
- a superseded pipeline;
- an ambiguous case that must remain `UNKNOWN`;
- a receipt that must be preserved;
- an unauthorized high-impact operation.

Compare against `perform-all`, status-only, cheapest-first, disable-all, and a planner that ignores leases. Promotion requires zero unsafe interventions, exact recovery of known terminals, lower or equal operational cost, deterministic replay, and explicit impossibility or unknown outputs when evidence is insufficient.
