# OCR HN Numeric Holdout v2

This experiment tests whether a lightweight pixel verifier can reduce equal-length numeric substitution errors by at least 10× on Honduran procurement documents with negligible overhead.

## Design

- One unique OCDS procurement record (OCID) is one statistical unit.
- One public PDF and one contiguous digit crop are selected per OCID.
- Selection never observes OCR output.
- Ground truth is taken from exact digit characters and coordinates in digitally generated PDF text.
- Pages dominated by a full-page image are excluded from this vector-truth tier.
- Tesseract runs once per selected page.
- Only spatially matched claims with the same digit length as truth enter the substitution-risk comparison.
- The verifier returns `ALIGNED`, `MISALIGNED`, or `INDETERMINATE`; uncertain claims abstain.
- URLs, hashes, OCIDs, institutions, pages, coordinates, crops, gates, and results are independently replayed.

## Image tiers

- `native_300`: direct 300-DPI render.
- `scan_stress_v1`: fixed OCR-independent downsample, blur, contrast reduction, JPEG compression, and geometry-preserving upscale.

A stress-tier result is scoped to that declared transform and must later transfer to an untouched native or naturally scanned holdout.

## Gate

A 10× result requires the candidate one-sided 95% upper risk bound to be no greater than one tenth of Tesseract's one-sided 95% lower risk bound on the same sealed units. It also requires minimum accepted count and coverage, leave-one-institution-out stability, and a separate one-digit counterfactual risk gate. No verifier threshold is tuned on the holdout.

A baseline with zero observed errors returns `BASELINE_TOO_CLEAN_TO_CERTIFY`; it is never relabeled as success.

Canary defaults: 120 unique OCIDs, 8 institutions, 40 accepted claims, 30% coverage, and counterfactual upper risk at most 3%.

Full protocol: 500 unique OCIDs, at least 10 institutions, at least 200 accepted claims, 30% coverage, and counterfactual upper risk at most 1%.

## Commands

```bash
python -m unittest -v ocr_hn_numeric_holdout_v1.test_holdout
python -m ocr_hn_numeric_holdout_v1.prepare --target-crops 120 --target-documents 120 --minimum-institutions 8
python -m ocr_hn_numeric_holdout_v1.evaluate ocr_hn_numeric_holdout_v1/run/preparation/manifest.json --pdf-cache ocr_hn_numeric_holdout_v1/run/preparation/pdfs --tier scan_stress_v1 --minimum-accepted 40
python -m ocr_hn_numeric_holdout_v1.verify ocr_hn_numeric_holdout_v1/run/preparation/manifest.json ocr_hn_numeric_holdout_v1/run/evaluation/evaluation.json --artifact-root ocr_hn_numeric_holdout_v1/run/evaluation
```

Constraints: public ONCAE/OCDS and HonduCompras sources only; external spend $0; no GCloud, GPU, paid OCR API, or production mutation. Logic Power and the Problem Solver select experiments and are absent from OCR runtime.
