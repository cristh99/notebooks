# FOR-ABS-001 F7 public verification capsule

This finite capsule independently verifies the non-sensitive receipts behind the proposed F7 promotion in private draft PR `cristh99/desktop-tutorial#13`.

## What it verifies

- four embedded SHA-256 receipts;
- four-source document manifest and source-hash uniqueness;
- six amount roles and exact HNL values;
- exact `100×` structured-value relationship;
- exact rounded `15%` performance guarantee;
- ordered opening → award → signed-contract chronology;
- five claim-evidence rows and five rival hypotheses;
- five correct amount observations reproduced under two OCR modes;
- five wrong-page, five wrong-role and five wrong-document attacks rejected;
- three byte-tampered source documents rejected;
- frozen promotion `F7 66→82`, total `655→671`;
- holdout opens, corruption claims, raw locator exports, network calls and external spend remain zero.

## Isolation

The capsule contains only commitment-based receipts, an independent verifier, tests and static/privacy checks. It does not contain source URLs, raw OCR text, actor names, credentials or original documents. Its execution performs no network calls and no external writes.

## Claim boundary

A PASS supports receipt integrity, arithmetic, cross-file lineage and the declared finite adversarial controls. It does not establish payment, acceptance, inventory, liquidation, settlement, illegality, corruption, investigative utility, temporal generalization or God Mode. Keep the verification PR draft and unmerged.

## Local commands

```bash
python -m compileall -q for_abs_f7_public_capsule
python for_abs_f7_public_capsule/static_validate.py
python for_abs_f7_public_capsule/verify.py
python -m unittest discover -s for_abs_f7_public_capsule -p 'test_*.py' -v
```
