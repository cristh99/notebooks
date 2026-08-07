# Stage 09 scale-up recovery protocol

This package supersedes the contested scale-up protocol in PRs #156/#158 without inspecting or selecting a new cohort.

## Why recovery is required

The shared Stage 09 environment already accessed outcome-bearing and identity-bearing fields, and candidate material was selected. The prior fixed seed and global blinding assertions are therefore not usable for a defensible preregistered sample.

## Recovery boundary

The protocol establishes one authority, requires a signed exclusion registry for every contaminated Flight receipt, separates exclusion/eligibility/randomness/selection/outcome/analysis roles, and waits for a future signed NIST Randomness Beacon pulse requested at or after `2026-08-08T00:00:00Z`.

No cohort is selected, no outcome is accessed, no inference is run, and Stage 10 remains blocked.

Canonical upstream: PR #153. Production modified: false. External cost: USD 0.00.
