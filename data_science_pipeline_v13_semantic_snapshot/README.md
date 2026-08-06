# Stage 08 — Semantic snapshot

This software-only capsule converts single-arbiter Stage 07 output into a deterministic analytical snapshot. It preserves event, amount and date roles (`CONTRACT`, `OBLIGATION`, `PAYMENT`, `RECEPTION`) so downstream analysis cannot silently add incomparable monetary concepts or double count the same economic chain.

The gate enforces explicit grain, HNL units, cutoff, lineage, missingness, role coherence, duplicate handling and leakage rejection. Synthetic fixtures do not constitute real procurement evidence and do not unblock Stage 09.
