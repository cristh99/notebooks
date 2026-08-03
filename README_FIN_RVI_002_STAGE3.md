# FIN-RVI-002 Stage 3 — sealed label-acquisition cohort

Stage 2 returned `OPEN`, not because the documentary policy lost, but because its random 20-row holdout contained **zero pre-existing adversarial gold labels**. Logic Power Problem Solver therefore selects the next minimal experiment: acquire a larger cohort that is labelable from original evidence without selecting on the eventual outcome.

## Selection before outcome inspection

From the full public ONCAE–SEFIN candidate universe:

1. exclude every Stage 1 holdout candidate;
2. exclude every contract/project code already present in the known adversarial cases;
3. use only candidate metadata available before object adjudication:
   - institution family (`SIT` or `FHIS`);
   - one-to-one versus multi-event cardinality;
   - amount-ratio bucket;
   - temporal-distance bucket;
   - deterministic SHA-256 order;
4. freeze 120 pairs under preregistered high-risk, medium-risk and control quotas;
5. cap each shared code at two pairs.

No supplier outcome, object compatibility, document text or final decision may affect selection.

## Independent evidence label

After freezing, acquire the highest-value official document available, preferring signed contracts and awards over notices. A conservative labeler distinct from the Stage 1 policy emits:

- `SUPPORTED` only with compatible supplier identity, payment language and strong object/document support;
- `REJECTED` only with a material supplier-identifier conflict or a hard object contradiction supported by original evidence;
- `UNRESOLVED` otherwise.

The policy under test remains the Stage 1 structured documentary adjudicator. The evidence label uses stricter exact-identity and extracted-document conditions.

## G07 gate

A candidate pass requires at least 20 confirmed positives and five confirmed negatives, zero challenger unsafe promotions, a strict unsafe-promotion reduction versus `CODE+SUPPLIER`, no lower supported recovery, a worse deterministic permutation control, Python/Node semantic agreement and a reproducible source manifest.

If any requirement fails, G07 remains `OPEN` and the report must expose the exact obstruction.

## Boundary

This experiment addresses attribution to `CONTRACTOR_PAYMENT`. It does not prove legality, receipt, quality, liquidation, fraud, corruption or physical result.
