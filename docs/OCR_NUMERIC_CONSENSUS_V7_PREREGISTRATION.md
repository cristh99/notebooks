# OCR numeric-consensus v7 — preregistration COCO-Text

## Status

`FROZEN_BEFORE_COCOTEXT_FOOTER_ROWS_OR_IMAGES`.

This is an engineering successor to the terminal TextOCR v6 FAIL. TextOCR,
CORD, SROIE, and WildReceipt are development or retired validation data and
cannot certify v7. No post-outcome repair receives scientific credit.

## Defects corrected before the new corpus

1. **No truth-length oracle:** inference eligibility receives only the detector
   match and its benchmark geometry; ground-truth transcription and its length
   are absent.
2. **Effective probability threshold:** every verified claim requires the
   digit forest minimum mean probability to be at least `0.25`.
3. **Verifier semantics:** v7 either returns the observed detector claim or
   abstains. It cannot replace the claim with alternate digits.
4. **Independent support:** the forest must reproduce the claim, the detector
   cluster must have no equal-length conflict, and at least one crop guard
   (`gray` or `autocontrast`) must reproduce the claim.
5. **Speed is measured, not presumed:** candidate and baseline wall time are
   recorded. A 10× speed claim requires a preregistered ratio
   `candidate/baseline <= 0.1`; otherwise no speed claim is permitted.

## Opened TextOCR development diagnostic — no credit

Bound evidence: terminal artifact `8961886770`, ZIP SHA-256
`899732a43cfc7f3889d441a8a639993eef58bc2e21d250e51a3a6c93f1b47921`.

- selected observations: `4,674`;
- v6: `217` accepted, `3` false, `114` counterfactual outputs;
- v6 hidden truth-length abstentions: `337`;
- v6 accepted below its declared threshold: `79`;
- v7 replay: `110` accepted, `1` false, `0` counterfactual outputs;
- v7 selected-denominator acceptance rate used only for conservative power
  projection: `110 / 4,674`.

The `337` oracle-abstained TextOCR cases lack downstream v6 channels, so they
cannot be post-hoc reconstructed. This is one reason a new untouched corpus is
mandatory.

## Untouched corpus

- repository: `Yesianrohn/OCR-Data`;
- component: `cocotext`;
- immutable revision:
  `2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c`;
- object: `data/cocotext-00000-of-00001.parquet`;
- exact bytes: `2,223,323,062`;
- SHA-256:
  `562176cbb803bb7aa140a4537701ef53ebb86e396c8927f9b160227ac49efd48`;
- annotations: CC BY 4.0; upstream image terms remain applicable.

Before freeze, only repository metadata may be read. The first post-freeze
operation is a Parquet metadata-column census that excludes the `image` column.

## Metadata-only power gate

The census selects at most one deterministic 4–12 digit risk unit per image
row using only `texts`, `bboxes`, `polygons`, and `num_text_regions`.

Full image download is blocked unless both hold:

- selected numeric units `>= 5,000`;
- projected verified claims `>= 400`, using the conservative opened-development
  rate `110/4,674`.

Failure is terminal for this corpus/version and preserves the candidate without
downloading image bytes.

## External quality gate, if power passes

- exact source size and SHA-256;
- encoded-byte and decoded-pixel SHA-256 deduplication;
- 12 partitions and 4 macrofolds;
- baseline errors must be positive;
- candidate upper risk bound must not exceed baseline lower bound divided by 10;
- selected coverage lower bound `>= 0.25`;
- counterfactual upper bound `<= 0.01`;
- at least 3 of 4 macrofolds pass;
- one execution only; no retuning after outcomes.

## Boundaries

The gate covers annotation-aligned 4–12 digit scene-text risk units. It does
not establish end-to-end OCR superiority, Honduras readiness, general document
layout quality, handwriting coverage, or production safety.

## Constraints

- external spend: `USD 0`;
- GCloud: forbidden;
- GPU: forbidden;
- paid OCR APIs: forbidden;
- production modification: forbidden;
- PR remains draft and unmerged until terminal evidence is audited.
