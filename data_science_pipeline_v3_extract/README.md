# Canonical Data Science pipeline v3 — Extract

This layer connects immutable raw PDFs to mandatory page rasterization, OCR, layout evidence, quality gates, and material quarantine.

## Frozen external canary

- Source: ONCAE `GUIA PARA LA MODALIDAD DE CONTRATACION DIRECTA`.
- Official URL: `https://oncae.gob.hn/wp-content/uploads/2024/11/GUIA-PARA-LA-MODALIDAD-DE-CONTRATACION-DIRECTA-1.pdf`.
- Known document length: 27 pages.
- Declared processing scope: first 3 pages only.
- Rasterization: mandatory even when the PDF has native text.
- Native text: non-authoritative quality control only.
- OCR: Tesseract `spa+eng`, PSM 6, 200 DPI.
- Gates: mean confidence ≥55, native-token recall ≥0.55, five identity tokens present, zero empty processed pages, cost USD 0.

Every page produces PNG, OCR text, TSV words/confidence, layout JSON, and native-text control. Every file is represented in the pipeline artifact registry with SHA-256 and exact parent lineage. Failures are quarantined rather than discarded.

No merge, mass processing, GCloud, paid compute, or post-result retuning is authorized by this canary.
