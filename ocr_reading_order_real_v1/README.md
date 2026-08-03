# OCR Reading Order Real v1

This is the next experiment selected by the verified **Logic Power Problem Solver v1** and Logic Power v10 under the user's hard constraints: zero external spend, no GCloud, no paid OCR API, and no new OCR runtime layer before the bottleneck is identified.

Logic Power and the Solver are development-time planners only. They are not imported by the ordering runtime.

## Question

The prior real canary found high text-region coverage but poor serialized-text accuracy. This experiment asks the minimum separating question:

> With perfect real block boxes but no text, images, or model inference, can geometry alone reconstruct human reading order?

A positive result means the next step is to apply the frozen geometry kernel to Tesseract boxes. A negative result means recognizer replacement is still unjustified; the next test must add block semantics or a lightweight layout-order model.

## Sealed design

- dataset: OmniDocBench v1.6 full annotation;
- pinned revision: `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec`;
- expected annotation SHA-256: `a45cd84b04ad8b793e775089640e6b681209abea33ead54c1828ddca35fae496`;
- deterministic split: `sha256(page_id)[0:8] mod 5 == 0` is holdout;
- candidate selection uses development pages only;
- the holdout is evaluated once with the frozen candidate set;
- inputs to every algorithm: page width, page height, block bounding boxes;
- no image pixels, OCR text, category semantics, model inference, GPU, GCloud, or paid API.

## Candidate family

- top-to-bottom/left-to-right baselines;
- row bands;
- recursive XY-cut variants;
- spanning-block bands with column recursion;
- geometric precedence ordering.

Selection is lexicographic on development data: official-style normalized reading-order edit, pairwise accuracy, exact-page rate, then lower complexity.

## Metrics

- OmniDocBench-style normalized edit distance over GT order indices;
- pairwise order accuracy;
- exact-page rate;
- layout- and document-type breakdowns;
- actual microseconds per page, excluded from the proof-carrying payload.

## Run

```bash
python -m unittest -v ocr_reading_order_real_v1.test_reading_order
python -m ocr_reading_order_real_v1.run_benchmark
python -m ocr_reading_order_real_v1.verify_report \
  ocr_reading_order_real_v1/run/reports/reading_order.json
```

## Promotion gate

Geometry is promoted only when the sealed holdout satisfies all of:

- mean reading-order edit `<= 0.10`;
- mean pairwise accuracy `>= 0.95`;
- exact-page rate `>= 0.60`;
- every layout type mean edit `<= 0.20`.

Otherwise the report returns `GEOMETRY_IS_PARTIAL` or `REJECT_GEOMETRY_ONLY` and names the next experiment. No production OCR change is made by this branch.
