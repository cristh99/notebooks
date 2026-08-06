# Data Science v11 — direct GitHub OIDC + Cosign preregistration

This branch closes only the trust and ordering layer for a fresh Stage 07 source.

It signs the canonical `PREREGISTRATION.json` directly with a short-lived GitHub
Actions OIDC identity and Sigstore/Cosign. The workflow requests the OIDC token
explicitly, validates safe claims without printing the token, installs a pinned
Cosign binary by SHA-256, creates a Sigstore bundle with transparency-log proof,
and verifies the exact repository, workflow, branch, commit, trigger, issuer and
certificate identity.

The signature establishes the exact preregistration record and workflow identity.
It does not prove that declarations inside the record are true, authenticate the
future PDF, validate OCR, validate resolution, authorize production, or unblock
Stage 08.

After a green signed-receipt run, the only legitimate next step is one bounded
resolution and full-document evaluation of the still-unopened official ONCAE
candidate. Keep the branch and PR draft and unmerged.
