# Stage 09 — preregistered scale-up protocol

The real two-row Analyze canary in PR #150 correctly terminated `NOT_EVALUABLE_MIN_CELL_SIZE`. This successor freezes the only legitimate next gate before any new outcome access.

Candidate discovery is blind to `bid_count`, `low_competition`, labels, rankings, and downstream outcomes. Eligible source-native contract events are stratified only by exact OCDS `procurementMethod`: `direct → DIRECT`, `open → OPEN`. A deterministic hash order freezes ten primary and ten reserve commitments per group, with a hard maximum of forty selected events.

Only after the cohort manifest is signed may a separate outcome-reveal lane read an explicitly reported integer `bid_count` and derive `low_competition = bid_count <= 1`. Empty tenderer arrays, missing fields, document counts, contract-payment links, or inferred competition never substitute for explicit bid count. Reserves activate only in their pre-frozen order.

The statistical plan remains H09-001, two-sided Fisher exact test, DIRECT-minus-OPEN risk difference, 95% Wilson intervals, Benjamini–Hochberg FDR q=0.05, and the frozen negative control. The analysis still fails closed unless each group has at least five evaluable contract events.

This package designs and signs the protocol only. It does not query the corpus, reveal outcomes, select a real cohort, run inference, authorize mass processing, modify production, or unblock Stage 10.
