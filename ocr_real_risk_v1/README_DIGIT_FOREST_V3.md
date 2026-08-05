# digit-forest-v3

Frozen, abstaining verifier for equal-length numeric OCR claims.

## Input

- OCR-produced numeric token crop;
- equal-length digit claim.

## Output

- accept only when all four deterministic view-averaged digit predictions equal the claim and every position probability is at least `0.25`;
- otherwise abstain.

## Frozen identity

- model: ExtraTreesClassifier, 500 trees;
- model SHA-256: `e1e3d8a9e1ff12206d5127c14053221225eb539c88072e40b1444b86b751bcce`;
- candidate SHA-256: `3ee998aa28a889d89462a5e970454dc1a21e964cb517c27a35b0b52a905c5cc0`.

## Status

External-validation candidate only. Do not deploy, tune on CORD, or claim 10× from SROIE development results.
