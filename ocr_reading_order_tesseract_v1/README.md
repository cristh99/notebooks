# OCR Reading Order Tesseract v1

This experiment is the exact next action emitted by OCR Reading Order Real v1 after geometry passed its sealed upper-bound test.

The algorithm is frozen as `xycut_loose`; it is not retuned after the geometry holdout. Tesseract runs once. The same recognized lines are then serialized in two ways:

```text
baseline: top-to-bottom, left-to-right
candidate: frozen recursive XY-cut
```

There is no second OCR pass, model download, GPU, paid API, GCloud use, or Logic Power code in runtime.

## Sealed sample

- source split: the same OmniDocBench holdout defined in PR #30;
- language: English pages, matching the installed Tesseract language pack;
- size: 50 pages;
- stratification: eight pages per available layout type, selected round-robin across document domains, then deterministic SHA-256 fill;
- algorithm source receipt: stable payload `7a60f4866be4d4a37f74a82acf40057277983b7523c2d61dd9de4c473d1cd8fa`;
- no candidate selection or threshold tuning occurs in this branch.

## Evaluation

Tesseract lines are matched geometrically to annotated text blocks. The report measures:

- conditional reading-order edit on matched blocks;
- coverage-aware reading-order edit;
- pairwise order accuracy;
- exact matched-block sequence rate;
- annotation-block match coverage;
- character and word accuracy of the serialized OCR text;
- Tesseract latency and additional XY-cut microseconds.

Raw Tesseract line text, boxes, confidence, image hashes and matches are preserved. The verifier recomputes all deterministic metrics and the promotion decision without rerunning OCR.

## Promotion rule

Promote to a sealed Honduran public-document holdout only if the frozen orderer:

- cuts conditional order edit by at least 20%;
- does not reduce mean character or word accuracy;
- harms no more than 10% of pages;
- matches at least 70% of annotated text blocks.

No production path is modified by this experiment.
