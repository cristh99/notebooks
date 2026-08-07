# Stage 09 preregistered scale-up

This branch freezes the next Analyze cohort before inspecting its eligibility counts or outcomes.

The hypothesis and statistics remain exactly those of PR #143: DIRECT versus OPEN low-competition rates, two-sided Fisher exact test, risk difference, 95% Wilson intervals, Benjamini–Hochberg FDR at 0.05, minimum cell size 5, and the existing negative control.

The cohort is limited to source-native ONCAE CONTRACT events in HNL. `bid_count` must be explicit: `numberOfTenderers`, or a non-empty exact tenderer list. An empty tenderer array is missing, never zero. One deterministic event per OCID prevents repeated tender-level outcomes from being counted as independent contracts.

The full official 2024 archive must be scanned before selecting the first 20 events per group by event hash. Optional stopping, outcome-driven threshold changes, causal claims, wrongdoing labels, rankings, production writes, and Stage 10 promotion are forbidden.
