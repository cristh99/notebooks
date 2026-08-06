# University Software Foundations Rocq runtime v1

This capsule closes one scoped runtime gate from the university curriculum: compile the official *Logical Foundations* source and representative new proofs with the real Rocq/Coq kernel.

## Official source contract

- Series: *Software Foundations*
- Volume: *Logical Foundations*
- Official version: `7.0` (`2026-01-09 13:17`)
- Required runtime: Coq/Rocq `9.0.0` or later
- Source: `https://softwarefoundations.cis.upenn.edu/current/lf-current/lf.tgz`
- Source SHA-256: `3721c1f9a25243251a30e3be9b861707c8e1ab4ba2d1e5374ca8ef36f8dcf130`
- Supported official runtime tag: `rocq/rocq-prover:9.0`

The source is now frozen. The next discovery run records the exact container digest behind the supported `9.0` tag. A further replay is required after that digest is committed to `SOURCE_LOCK.json`; only that replay may be promoted to final scoped PASS.

## Gates

1. Download the official tarball and retain it in the evidence artifact.
2. Enforce its SHA-256.
3. Record and subsequently enforce the Rocq container digest.
4. Build the official volume once with `make -j1` and once independently with `make -j4`.
5. Compile `Runtime.v` in both trees and compare normalized `Print Assumptions` output.
6. Reject `NegativeControl.v` in both trees.
7. Reject `Admitted`, `admit`, `Axiom` or `Parameter` declarations in the scoped runtime file.
8. Count but do not erase or misrepresent placeholders in the official instructional source.
9. Emit a manifest, receipt and SHA-256 ledger.

## Scope boundary

A final passing run establishes real Rocq kernel execution for the scoped exercises and successful serial/parallel builds of the downloaded official volume. It does **not** establish that every official exercise was solved, that every `Admitted` placeholder was replaced, or that the full Cambridge/UCL curriculum is complete.
