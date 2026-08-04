# OCR Real Risk Holdout v1

This package evaluates numeric OCR on public Honduran procurement PDFs.

The canary uses SHA-256 partitions 0–9. Partitions 10–99 remain untouched for final evaluation. Each document contributes one numeric location selected before OCR. The report uses exact simultaneous confidence bounds and preserves source hash, page, bounding box, crop and decision.
