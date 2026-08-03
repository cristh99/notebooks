# OCR Reading Order Honduras v1

This is the first domain-transfer gate for the frozen reading-order kernel. It uses only official public Honduran procurement documents and zero-cost local software.

## Why a new holdout is necessary

The historical Honduran OCR holdout was recorded on an ephemeral VM path and no durable hash/readback remains. It cannot support a fresh claim. This branch therefore creates a new public holdout without GCloud.

## Frozen before review

The manifest was committed before downloading, rendering, or inspecting any selected page. It contains ten PDFs from five pre-existing FIN-RVI-002 holdout processes, with two fixed document-type slots per process:

- tender notices;
- bidding documents;
- clarification;
- opening acts;
- award notices;
- signed contract.

The source identities come from an existing public, prospectively selected financial holdout rather than from OCR performance.

## Stage A — preparation

For each declared URL, GitHub Actions:

1. downloads the PDF with a 25 MB hard cap;
2. validates `%PDF-`, records bytes, headers and SHA-256;
3. renders only page 1 at 150 DPI;
4. runs Tesseract once with Spanish + English;
5. groups words into Tesseract blocks;
6. records baseline y/x and frozen `xycut_loose` orders;
7. produces a numbered overlay and blank annotation template;
8. fails closed unless at least eight documents are prepared.

This stage computes no performance score and changes no production path.

## Stage B — sealed evaluation

After Stage A is archived, the visible overlays are annotated once with the correct block order. The annotation may not add, remove, merge, split or rename blocks, and every available block ID must appear exactly once. The evaluator then compares the two already-frozen permutations.

The annotation is agent-generated visual ground truth, not independent human review. That limitation is explicit and blocks a claim of independent external validation.

## Constraints

- external spend: `$0`;
- GCloud: forbidden and unused;
- paid APIs: unused;
- GPU: unused;
- one Tesseract pass per page;
- Logic Power and the Problem Solver remain outside runtime;
- no production modification or merge requested.
