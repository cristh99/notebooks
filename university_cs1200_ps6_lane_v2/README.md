# University CS1200 PS6 lane v2

This lane converts the frozen PS6 preflight into an executable public-source
receipt. It reuses the existing canonical PS6 knowledge page and adds the missing
validation layer rather than creating a duplicate course resource.

## Frozen source

- Repository: `Harvard-CS-1200/2026-Spring`
- Commit: `0b967fe320ecf2141a6f3b8165d3d096c99fb3ac`
- Exact file hashes: `SOURCE_LOCK.json`

## Gates

1. Verify official commit, tree, starter, tests, helpers, experiment script and
   problem statement hashes.
2. Overlay the repaired official-compatible `ps6.py` without modifying the source
   repository.
3. Run the exact public 2-color and 3-color tests.
4. Reject every functional public-test failure; retain declared 3-color timeouts.
5. Run independent exhaustive oracles serially and with four workers.
6. Compare scientific payloads exactly.
7. Validate interval coloring, maximal independent sets, preset color classes and
   the official Bron-Kerbosch defect.
8. Run a bounded experiment on both official graph-generator families.
9. Emit one receipt and a complete SHA-256 ledger.

## Status semantics

`PASS_SCOPED_PS6_MANDATORY_TECHNICAL_LANE` closes the mandatory public technical
lane only. Personal reflection, optional survey, private graders, official course
grade and exhaustive course completion remain outside scope.
