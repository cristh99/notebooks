# OCR numeric-consensus v7 — untouched LSVT power gate

## Authority

The behavioral authority is the frozen COCO-Text v7 candidate with stable
payload `33d14875f0d2f9681ced662e452a5f28943ecb65e30a9242663d6a472034da9d`.
COCO-Text ended as a terminal power failure before image download. This LSVT
binding changes no policy, model, threshold, quality gate, or speed gate.

Exact policy source SHA-256:
`5b37aa3ac9f349e708624e815dab97e2ab1eaaac4a905499de15aa3513862b2d`.

## Untouched source

- dataset: ICDAR-2019 LSVT;
- mirror repository: `Yesianrohn/OCR-Data`;
- revision: `2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c`;
- object: `data/LSVT-00000-of-00001.parquet`;
- exact bytes: `8,979,134,697`;
- SHA-256:
  `44d4e6822060bbd3c11b933675d91ac7da4e944645bee7a080529f0232823c8b`;
- upstream license: CC-BY-NC-ND-3.0; research and non-commercial use only;
- source images must not be redistributed.

Before freeze, only repository object metadata may be read. The first
post-freeze operation reads only Parquet metadata columns `texts`, `bboxes`,
`polygons`, and `num_text_regions`; the image column remains excluded.

## Unchanged power gate

Full image download is blocked unless both hold:

- selected deterministic 4–12 digit risk units `>= 5,000`;
- projected verified claims `>= 400`, using the frozen no-credit development
  rate `110/4,674`.

Failure is terminal for LSVT v7 and must not change thresholds or selection.

## Unchanged external quality and speed gates

If and only if power passes:

- candidate upper risk bound <= baseline lower risk bound / 10;
- selected coverage lower bound >= `0.25`;
- counterfactual upper bound <= `0.01`;
- four macrofolds, at least three pass;
- candidate and baseline wall time measured;
- a 10× speed claim requires candidate/baseline wall-time ratio <= `0.1`;
- one execution, no post-outcome retuning.

## Mechanical runner repair — no scientific credit

The first two hosted-runner attempts ended before `checkout`: GitHub did not
acquire an `ubuntu-24.04` runner and executed zero workflow steps. After both
terminal infrastructure failures, the workflow changed only the runner label
to `ubuntu-22.04` and enabled same-branch concurrency cancellation. No source,
sample, policy, model, threshold, quality gate, speed gate, or outcome changed;
no LSVT footer, row, transcription, geometry, image byte, OCR output, or
benchmark outcome had been opened.

## Constraints

External spend `USD 0`; no GCloud, GPU, paid OCR API, commercial use,
production modification, image redistribution, Honduras-readiness claim, or
general OCR superiority claim. The PR remains draft and unmerged through
terminal audit.
