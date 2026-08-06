# Stage 09 — Analyze contract

This software-only capsule analyzes only the preregistered `CONTRACT / CONTRACT_VALUE / CONTRACT_DATE` population from a role-preserving Stage 08 snapshot. Obligations, payments and receptions are reported as exclusions and are never silently added to contract values, preventing economic double counting.

The analysis freezes its hypothesis, baseline, population, Fisher exact test, Wilson uncertainty, Benjamini–Hochberg correction, deterministic negative control and median/MAD review candidates. All findings remain association-only, synthetic and review-gated; Stage 10 stays blocked.
