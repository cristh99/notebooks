# CORD untouched validation protocol v1

## Purpose

Evaluate the already frozen `digit-forest-v3` candidate on an external receipt corpus without changing its model, threshold, views, feature extractor, claim scope or acceptance rule.

## Isolation

Before any CORD OCR outcomes are opened, the validation implementation must bind:

1. the frozen candidate stable-payload SHA-256;
2. the model-file SHA-256;
3. the exact CORD repository revision and source-file SHA-256 values;
4. an outcome-blind deterministic selector;
5. one physical numeric location per receipt;
6. the full statistical gate below.

No CORD image, annotation or OCR result may be used for training, threshold selection, preprocessing selection, model selection or debugging before the first terminal report is sealed.

## Unit of inference

One deduplicated physical numeric annotation from one receipt image. Duplicate images or duplicate physical evidence count once. Conflicting truths fail closed.

## Eligible claim

A spatially matched Tesseract claim is eligible only when:

- the claim and truth are digit-only;
- both have equal length;
- the matched OCR box meets the frozen spatial-coverage requirement;
- the verifier receives only the OCR-produced crop and the claim;
- annotation coordinates are used only for selection, matching and scoring.

Length mismatch, absent spatial match and low spatial coverage are abstentions, not errors or accepted claims.

## Candidate

- Candidate ID: `digit-forest-v3`
- Model SHA-256: `e1e3d8a9e1ff12206d5127c14053221225eb539c88072e40b1444b86b751bcce`
- Candidate stable-payload SHA-256: `3ee998aa28a889d89462a5e970454dc1a21e964cb517c27a35b0b52a905c5cc0`
- Threshold: `0.25`
- Views: original, autocontrast ×2, CLAHE ×2, Otsu ×2
- Acceptance rule: every averaged four-view digit argmax equals the claim and the minimum position probability is at least `0.25`

## Primary statistical gate

Use simultaneous one-sided exact Clopper–Pearson bounds with the predeclared alpha allocation used by the frozen evaluator.

A positive external result requires all of the following:

1. at least `300` deduplicated eligible natural claims;
2. at least one observed natural baseline error;
3. at least `100` candidate accepts;
4. lower exact coverage bound over all selected locations ≥ `25%`;
5. candidate natural false-accept upper bound ≤ one tenth of the baseline natural-error lower bound;
6. counterfactual false-accept upper bound ≤ `1%`;
7. zero overlap with all SROIE training and development images by exact and perceptual identity checks;
8. all hashes, denominators and statistical calculations replay independently;
9. no threshold, model, feature or preprocessing changes after the source manifest is sealed.

## Interpretation

A pass establishes external transfer for the narrow equal-length numeric substitution task on CORD receipts. It does not establish Honduras readiness, general OCR superiority, full-document accuracy or production readiness. A failure or insufficient denominator triggers abstention and diagnosis; it does not authorize retuning on CORD followed by a claim on the same data.

## Constraints

- external spend: `$0`;
- GCloud: prohibited;
- GPU: not required;
- paid OCR APIs: prohibited;
- production changes: prohibited.
