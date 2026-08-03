# OCR God 10X v1

This branch tests the only remaining zero-cost path that can plausibly deliver an order-of-magnitude improvement on unique raster pages: a persistent PP-OCRv6 CPU engine with OpenVINO high-performance inference, followed by a selective quality cascade only if the fast tier proves viable.

Logic Power v10 and Logic Power Problem Solver v1 are development-time planners only. They are never imported by OCR runtime.

## Claims are gated, not assumed

A final `10x` claim requires the same sealed pages and hardware to satisfy all of the following:

- cold unique-page throughput at least `10x` the Tesseract 300-DPI baseline after one persistent-engine initialization;
- numeric error `(1 - F1_numeric)` no more than one tenth of baseline;
- order-independent word error `(1 - F1_word_bag)` no more than one tenth of baseline;
- no worse completeness and no additional catastrophic pages;
- no native-text inference, result cache, repeated pages, paid API, GPU, or GCloud counted in the primary result.

Warm cache and native-text routing may be reported separately but cannot establish the cold-raster claim.

## Stage 0: viability smoke test

Before downloading a benchmark corpus, public GitHub Actions installs official PaddleOCR 3.7.0, PaddlePaddle 3.2.0 and the CPU high-performance plugin, then runs `PP-OCRv6_tiny` persistently on a deterministic Spanish numeric page. The stage fails closed if:

- the official tiny detector/recognizer cannot initialize with high-performance inference;
- output is empty or contains no numeric token;
- a second in-process inference cannot complete;
- the evidence report cannot be written.

Only a passing smoke test opens the sealed real-page benchmark.

## Constraints

- external spend: `$0`;
- GCloud: forbidden and unused;
- paid OCR APIs: unused;
- GPU: unused;
- branch and PR remain isolated, draft and unmerged.