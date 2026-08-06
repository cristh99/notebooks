# OCR numeric-consensus v7 — OpenVINO preregistration

## Status

`FROZEN_BEFORE_OPENVINO_FOOTER_ROWS_OR_IMAGES`.

COCO-Text v7 closed as `UNKNOWN_NO_IMAGE_OUTCOMES_OPENED` because its metadata-only census found only 998 selectable rows and projected 23.49 verified claims. That result does not alter the v7 policy, thresholds, metrics, or speed gate. COCO-Text, TextOCR, CORD, SROIE, and WildReceipt are retired from scientific promotion.

## Frozen candidate

The same v7 claim verifier is retained without retraining or retuning:

- no annotation truth or truth-text length at inference;
- effective digit-forest minimum mean probability `>= 0.25`;
- verify the detector claim or abstain; never substitute alternate digits;
- equal-length detector conflict causes abstention;
- at least one independent crop guard reproduces the claim;
- 10× speed claim requires measured `candidate/baseline wall time <= 0.1`;
- 10× quality claim requires the preregistered statistical bounds, not a green workflow.

Opened TextOCR replay remains development-only: `110/4,674` accepted, one false accepted, zero counterfactual outputs. It supplies only the conservative power projection and receives no scientific credit.

## Untouched corpus

- repository: `Yesianrohn/OCR-Data`;
- component: `openvino`;
- immutable revision: `2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c`;
- object: `data/openvino-00000-of-00001.parquet`;
- exact bytes: `65,751,927,475`;
- declared rows for this exact LFS object: `207,790`;
- SHA-256: `5413c6ffb4f8047977db9dba520453976f48eed91b5477d06e7f62258a2ba09c`;
- repository metadata only may be read before freeze;
- upstream image terms must be reviewed before any full image download.

The OpenVINO component has not been used to train or tune the frozen digit forest. Pixel overlap cannot be checked before images are authorized, so any later full gate must deduplicate encoded bytes and decoded pixels against prior opened corpora before credit.

## Two-stage metadata-only power gate

The image column is forbidden in both stages.

### Stage A — texts-only upper bound

Read only `texts` and row index. Require exactly `207,790` rows, then count image rows containing at least one frozen-scope 4–12 digit transcription. This is an upper bound: geometry validation can remove candidates but cannot create a candidate absent from the text list.

If the upper bound cannot satisfy both conditions, the corpus/version closes without reading geometry:

- selected numeric image rows `>= 5,000`;
- projected verified claims `>= 400` using exactly `110/4,674`.

The second condition requires at least `16,997` selectable rows.

### Stage B — exact geometry census

Run only if Stage A can pass. Require the second scan to contain exactly `207,790` rows; read only `texts`, `bboxes`, `polygons`, and `num_text_regions`; apply the byte-identical TextOCR v6 deterministic geometry/selection code; select at most one risk unit per image row; then adjudicate the same frozen power thresholds exactly.

Passing the metadata gate makes the corpus eligible only for a separately preregistered full external workflow after artifact audit and license review. This metadata workflow never authorizes or downloads images, never runs OCR, and never creates a scientific verdict.

## External quality gate, only after separate authorization

- exact source size and SHA-256;
- encoded-byte and decoded-pixel deduplication;
- 12 partitions and 4 macrofolds;
- positive baseline error count;
- candidate simultaneous upper risk bound no greater than baseline simultaneous lower bound divided by 10;
- selected coverage simultaneous lower bound `>= 0.25`;
- counterfactual simultaneous upper bound `<= 0.01`;
- at least 3 of 4 macrofolds pass;
- measured candidate/baseline wall-time ratio `<= 0.1` for any 10× speed claim;
- one execution only; no retuning after outcomes.

## Boundaries and constraints

The prospective gate concerns annotation-aligned 4–12 digit text units in this component. It does not establish end-to-end OCR superiority, document-layout quality, handwriting coverage, Honduras transfer, production readiness, or fraud detection.

- external spend: `USD 0`;
- GCloud: forbidden;
- GPU: forbidden;
- paid OCR APIs: forbidden;
- production modification: forbidden;
- PR remains draft and unmerged until terminal artifact audit.
