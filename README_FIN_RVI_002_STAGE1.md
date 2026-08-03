# FIN-RVI-002 Stage 1 — public-data prospective holdout

This capsule applies Logic Power v10 as a **meta-controller**: it executes the real experiment selected to attack Finance gates G07 and G09. Logic Power is not embedded inside a financial model.

## Protocol

1. Download official OCP Registry OCDS packages for Honduras ONCAE (publication 122) and SEFIN (publication 123), years 2023–2025.
2. Build a release-level identity index without using supplier identity or object compatibility to select the holdout.
3. Generate candidate ONCAE–SEFIN pairs using only:
   - a canonical institutional alias for SIT, FHIS/SEDECOAS, or ENP;
   - an exact shared contract or project code;
   - a maximum 366-day temporal distance;
   - amount difference retained only as a diagnostic, because legitimate events can be advances or partial payments.
4. Preserve observed cardinality: one contract/project may have several financial events.
5. Freeze up to 20 candidate pairs before object inspection: half for breadth across codes, then within-code ambiguity, then deterministic fill under a declared SHA-256 seed.
6. Only after freezing, inspect supplier identity, procurement/financial object text, classifications, and document metadata.
7. Compare:
   - baseline: every shared-code candidate is a contractor payment;
   - evidence policy: promote only supplier- and object-supported pairs; reject or abstain otherwise.
8. Attempt one public document download per holdout pair and record URL, bytes, time, content type, and SHA-256.

## Hard boundary

An automated object-consistency decision is not a human label and does not prove legal payment, delivery, receipt, legality, or physical result. G07 can only become a candidate pass pending independent replay; G09 remains open until prior-art and replication gates close.

## Reproduce

```bash
python -m unittest discover -v -s fin_rvi_002_stage1 -p 'test_*.py'
python -m fin_rvi_002_stage1.run_stage1_v2 \
  --output reports/fin_rvi_002_stage1 \
  --years 2023 2024 2025 \
  --max-days 366 \
  --holdout-size 20
```
