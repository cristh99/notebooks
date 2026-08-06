# Data Science pipeline v9 — evidence-scoped resolution policy

This bounded Stage 07 maintenance layer separates four evidence channels before resolving a claim:

1. source provenance;
2. document metadata;
3. OCR content;
4. native-text diagnostic control.

It repairs the semantic defects exposed by the SESAL and PACC canaries. Metadata may identify a source or remain a candidate, but it cannot silently become a content mention. Absence in a partial page scope causes abstention, while a token present in native control but missed by OCR quarantines the OCR candidate.

Two structural controls prevent policy bypass:

- every validated channel carries a canonical receipt that binds channel, observation hash, validator identity and policy hash;
- claim scope fixes which channels may confirm source identity or document content, so metadata or provenance cannot be reconfigured into content evidence.

Observation text and validation receipts are snapshotted immutably so later mutation cannot rewrite a decision.

## Reproduce

```bash
cd data_science_pipeline_v9_evidence_scope
python verify.py
```

The verifier checks frozen source/test hashes, runs every behavior test, compiles the module and emits `evidence/receipt.json` plus its SHA-256.

## Verified locally

- 15/15 behavior, adversarial and determinism tests pass;
- Python compilation passes;
- canonical receipt replay is byte-identical;
- receipt verdict: `PASS_SOFTWARE_POLICY_ONLY`;
- external cost USD 0.00.

## Claim boundary

This is a software-governance repair. It does not validate a fuzzy resolver, authenticate the validator identity cryptographically by itself, authorize production, reopen exposed documents, or earn external/scientific promotion credit. A fresh preregistered document and validator binding remain required.
