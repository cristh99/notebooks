# OCR Numeric Rescue v1

## Core

The real-page canary rejected full-page PP-OCRv6 medium: it was `30.827×` slower than Tesseract and slightly worse in aggregate text/layout metrics, while improving numeric-sequence accuracy by `3.921` percentage points.

Logic Power v10 is used only **offline** to select the next experiment. It is not imported, invoked, or charged to OCR inference.

The selected experiment is the minimum targeted test of the surviving advantage:

```text
Tesseract full page
→ crop only words containing one numeric token
→ PP-OCRv6-small recognition only on those crops
→ compare or conservatively rescue
```

No second full-page detector runs.

## Frozen evidence source

- source PR: `cristh99/notebooks#11`;
- source run: `30833428126`;
- source artifact: `8864530547`;
- artifact SHA-256: `6a5459ed4e004c4fe7f7a0692ad6d8b7dd67ef51bb0ca9a5afc4185fb10f47b7`;
- source stable payload: `850d97ca9183a0ea4a1dbd834cc1a1f824db2cbd0db717453285f5f48030cbd9`;
- same OmniDocBench revision and same eight pages.

## Runtime policy under test

The small model may propose a replacement only when:

- the crop and both outputs contain exactly one numeric token;
- PP-OCRv6-small confidence is at least `0.95`;
- Tesseract confidence is at most `0.80`;
- the tokens disagree.

The policy is fixed before outcomes. Ground truth is used only afterward to classify a proposal as a true correction, harmful change, non-correction, or unscorable change.

## What the report measures

- numeric candidates discovered from Tesseract boxes;
- baseline matches, substitutions, insertions and deletions under exact edit alignment;
- raw rescue and harm opportunities from the small recognizer;
- disagreement precision and recall on baseline substitutions;
- strict proposed changes, true corrections and harmful changes;
- page-level numeric sequence accuracy before/after the fixed policy;
- Tesseract latency, recognition-model cold start and incremental crop latency;
- exact input/model/environment provenance.

## Promotion rules

- **Promote conservative correction:** positive numeric delta, zero harmful changes, and materially lower incremental latency than full-page PP-OCRv6 medium.
- **Promote flag-only mode:** disagreements capture errors with useful precision/recall, but automatic replacements are not safe.
- **Reject the branch:** no measurable correction/flagging power or unacceptable latency.

No result from eight pages authorizes a global SOTA claim or direct production deployment.

## Run

```bash
python -m unittest -v ocr_numeric_rescue_v1.test_rescue
python -m ocr_numeric_rescue_v1.run_canary --output-dir ocr_numeric_rescue_v1/run
python -m ocr_numeric_rescue_v1.verify_report ocr_numeric_rescue_v1/run/reports/numeric_rescue.json
```

## Cost boundary

- external spend: `$0`;
- GCloud: forbidden and unused;
- paid OCR APIs: unused;
- GPU: unused;
- public GitHub Actions CPU only.
