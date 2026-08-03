# FIN-RVI-002 Stage 1 — public-data prospective holdout

This capsule applies Logic Power v10 as a **meta-controller**: it executes the real experiment selected to attack Finance gates G07 and G09. Logic Power is not embedded inside a financial model.

## Protocol

1. Download official OCP Registry OCDS packages for Honduras ONCAE (publication 122) and SEFIN (publication 123), years 2023–2025.
2. Build a release-level identity index without looking at object descriptions.
3. Generate candidate ONCAE–SEFIN pairs using only:
   - same source year;
   - exact normalized buyer and supplier identity;
   - closest amount difference at most 5%;
   - closest date difference at most 366 days.
4. Keep strict one-to-one candidates.
5. Freeze up to 20 candidates by a declared SHA-256 seed.
6. Only after freezing, inspect procurement/financial object text and document metadata.
7. Compare:
   - baseline: every identity/amount/date candidate is a contractor payment;
   - evidence policy: promote only object-supported pairs; reject or abstain otherwise.
8. Attempt one public document download per holdout pair and record URL, bytes, time and SHA-256.

## Hard boundary

An automated object-consistency decision is not a human label and does not prove legal payment, delivery, receipt or physical result. G07 can only become a candidate pass pending independent replay; G09 remains open until prior-art and replication gates close.

## Reproduce

```bash
python -m unittest -v fin_rvi_002_stage1.test_stage1
python -m fin_rvi_002_stage1.run_stage1 --output reports/fin_rvi_002_stage1
```
