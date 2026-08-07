# FOR-ABS-001 — public forensic-finance verification capsule

This capsule publishes bounded, non-sensitive receipts for a forensic-finance program using Honduras public evidence. It does **not** publish source documents, identities, private signals, or restricted records.

## Absolute goal

A 1000/1000 forensic-finance system would reconstruct financial and evidentiary chains, detect adaptive corruption mechanisms, beat strong international baselines on real data, generate reproducible evidence packets, generalize across jurisdictions, and demonstrate externally confirmed impact without turning risk signals into accusations.

Current absolute score: **580/1000**.

## Evidence contract

Only three states are allowed:

- `POSITIVE_CANDIDATE`: externally evidenced forensic-review outcome with declared provenance;
- `UNLABELED`: no sufficient external evidence; never equivalent to clean;
- `UNRESOLVED`: identity, date, linkage, or scope is insufficient.

The public capsule forbids `CLEAN`, `CORRUPT`, and `FRAUD_PROVEN` as automatic states.

## Executed gates

### Stage 0 — mult-source readiness

- 1,789 relevant tables;
- procurement, financial flows, identity, documents, and external evidence present;
- typed shared join keys;
- no writes and no corruption labels.

### Stage 1 — TSC evidence audit

- 5,084 documents and 95,785 candidate pages;
- 16,065 responsibility/reparo pages;
- 7,326 recovery/perjuicio pages;
- 14,538 finding pages;
- source document, page, hash, context, and OCR provenance available.

### Stage 2 — provenance-complete positive-cohort preflight

- 71 priority documents with matching hashes, dates, and institution metadata;
- 69 provenance-complete positive-candidate documents;
- 590 provenance-complete responsibility/recovery pages;
- deterministic eligible-rowset SHA-256:
  `dbbdb9e288d3048ed26db9c8860ae41150f39a4d975bf232df9de28801c91392`.

This authorizes cohort freezing and linkage experiments. It does not prove corruption or grant score points by itself.

## Reproduce

```bash
python -m compileall -q for_abs_001_public
python -m unittest -v for_abs_001_public.test_contracts
python -m for_abs_001_public.verify_receipts
```

## Next experiment

Freeze the provenance-complete TSC cohort, link it to ONCAE and SEFIN through typed institution, contract, supplier, document, date, and amount evidence, then compare random ranking, amount ranking, red flags, network features, weak supervision, and positive-unlabeled learning under temporal, institutional, and entity-separated evaluation.
