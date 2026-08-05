# Digit Forest v3 — frozen candidate result

## Status

`FROZEN_FOR_UNTOUCHED_EXTERNAL_VALIDATION_ONLY`

This candidate is a development result, not a production release and not a formal 10× certificate. SROIE outcomes were already available during development; only a separate untouched external dataset can support the next claim.

## Frozen design

- Model: `ExtraTreesClassifier`, 500 trees, random state `20260804`.
- Input: the OCR-produced numeric token crop plus an equal-length digit claim.
- Views: original grayscale, autocontrast ×2, CLAHE ×2 and Otsu ×2.
- Feature: frozen 1,564-dimensional HOG/low-resolution/projection vector per digit position.
- Decision: accept only when every averaged four-view digit prediction equals the claim and the minimum position probability is at least `0.25`.
- Truth and annotation boxes are unavailable to inference.

## Reproducible development evidence

| Measure | Result |
| --- | ---: |
| Selected SROIE locations | 845 |
| Equal-length eligible claims | 571 |
| Baseline Tesseract errors | 63 |
| Company-disjoint train OOF accepts | 222 / 355 |
| Train natural false accepts | 0 |
| Train counterfactual false accepts | 0 |
| Train-only model on SROIE test accepts | 140 / 216 |
| Test natural false accepts | 0 |
| Test counterfactual false accepts | 0 |
| Combined out-of-sample accepts | 362 / 571 |
| Combined natural false accepts | 0 |
| Combined counterfactual false accepts | 0 |
| Coverage of all selected locations | 42.8402% |
| Simultaneous 95% selected-coverage lower bound | 39.0042% |
| Simultaneous 95% natural-risk upper bound | 1.2032% |
| Simultaneous 95% counterfactual-risk upper bound | 0.7645% |
| Development reduction lower bound if treated as validation | 6.8728× |

## Frozen identities

- Model SHA-256: `e1e3d8a9e1ff12206d5127c14053221225eb539c88072e40b1444b86b751bcce`
- Candidate stable-payload SHA-256: `3ee998aa28a889d89462a5e970454dc1a21e964cb517c27a35b0b52a905c5cc0`
- Development-report stable-payload SHA-256: `f83dcf37703cb447ec390dec096cc7dff4f0ea61b7ccab92fc0cb35f4507fb1e`
- Training receipt-set SHA-256: `5764fbb4f3c6cef9bccc8024f158b7d1957d404c65666c9844fda1fe02c07c57`

## Decision

The learned verifier is materially stronger than the prior handcrafted consensus candidate and is frozen for one untouched external evaluation. It has not established 10×: the simultaneous development lower bound is `6.8728×`, and development data cannot serve as the final certificate.

No production path changed. External spend: `$0`. GCloud, GPU and paid OCR APIs were not used.
