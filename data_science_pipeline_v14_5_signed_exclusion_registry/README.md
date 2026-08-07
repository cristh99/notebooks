# Stage 09 contamination exclusion registry

This package is the noncompensable successor gate to recovery protocol PR #161.

It freezes the exact eight contaminated Flight receipts and their Flight/run provenance as a receipt-wide exclusion registry. Because individual candidate commitments were not preserved in canonical coordination, the safe rule is broader: every row or candidate derived directly or transitively from any listed receipt or Flight/run is excluded. A future candidate without complete receipt, Flight ID and run provenance also fails closed.

The registry does not query candidates, inspect outcomes, consume the future NIST beacon, select a cohort, run analysis, modify production, or unblock Stage 10. The next gate is a signed NIST Randomness Beacon 2.0 pulse at or after 2026-08-08T00:00:00Z, followed by role-separated commitment-only selection against this signed registry.
