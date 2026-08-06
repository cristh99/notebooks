# Data Science pipeline v9 — evidence-scoped resolution policy

This bounded Stage 07 maintenance layer separates four evidence channels before resolving a claim:

1. source provenance;
2. document metadata;
3. OCR content;
4. native-text diagnostic control.

It repairs the semantic defect exposed by the SESAL and PACC canaries: metadata may identify a source or remain a candidate, but it cannot silently become a content mention; absence in a partial page scope causes abstention, while a token present in native control but missed by OCR quarantines the OCR candidate.

## Verified locally

- 8/8 behavior tests pass;
- Python compilation passes;
- deterministic canonical receipt serialization passes;
- external cost USD 0.00.

## Claim boundary

This is a software-governance repair. It does not validate a fuzzy resolver, authorize production, reopen exposed documents, or earn external/scientific promotion credit. A fresh preregistered document is still required.
