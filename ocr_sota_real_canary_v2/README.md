# OCR SOTA Real Canary v2

This is the next experiment selected by the offline Logic Power v10 strategy: compare open OCR families on the same real, annotated pages before training or redesigning anything.

## What it does

- resolves one exact OmniDocBench dataset revision at runtime;
- deterministically selects eight English pages spanning tables, formulas, fuzzy scans, notes, multi-column and ordinary layouts when available;
- downloads only those pages;
- runs Tesseract 5.5 and PaddleOCR 3.7 / PP-OCRv6 on CPU;
- scores character accuracy, word accuracy, numeric-token preservation, text-region coverage, latency and provenance;
- emits a report whose stable payload is independently rebuilt and hash-verified.

The canary is a component comparison, **not** an official OmniDocBench leaderboard submission. It does not score table TEDS or formula CDM yet.

## Constraints

- external spend: `$0`;
- no GCloud;
- no paid OCR API;
- no GPU;
- public GitHub Actions runner only;
- eight pages, two engines, sixteen page-engine results.

## Run

```bash
python -m unittest -v ocr_sota_real_canary_v2.test_canary
python -m ocr_sota_real_canary_v2.run_canary --pages 8
python -m ocr_sota_real_canary_v2.verify_report ocr_sota_real_canary_v2/run/reports/canary.json
```

## Promotion rule

This canary determines the next move:

- if PP-OCRv6 dominates Tesseract broadly, build the free page-type router;
- if gains cluster by page type, route selectively;
- if both fail on the same residual class, create a sealed Honduran holdout and only then consider adaptation;
- no SOTA claim is allowed from this canary alone.
