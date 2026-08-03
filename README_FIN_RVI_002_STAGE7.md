# FIN-RVI-002 Stage 7 — clean reconstruction of the third cohort

Stage 6 reproduced the bounded safety–recovery result on a third preregistered cohort that excluded all `237` shared codes used by Stage 3 and Stage 4. Stage 7 is the final clean reconstruction required by the fail-closed G09 contract.

## Frozen source

- Stage 6 head: `9beb7ec13e09674ea95d7a517f038acb37b9653b`;
- public run: `30847688470` — SUCCESS;
- artifact: `8869552099`;
- artifact SHA-256: `ad221e7cafb7fc8d11afb5e53f486842788f0fa5a423fbdb9891f9dc7824dfaf`.

## Exact reference

- candidate universe: `2,295`;
- cohort: `120`;
- prior codes excluded: `237`;
- labels: `63 SUPPORTED / 28 REJECTED / 29 UNRESOLVED`;
- baseline: `19` unsafe, `63/63` recovered;
- policy v3: `0` unsafe, `63/63` recovered, `0` missed;
- permutation: `22` unsafe, `41` recovered;
- independent policy mismatches: `0`.

Frozen hashes:

- compact rows file: `90e26745ced9dafd81249edb39ffbd4c10f0b64a5c6855eadf6053c4abf503e3`;
- labels file: `fc3a33ba87ecc29a909717e4702ea3e281d5461fa2c5d45e242f9be8a4dc7f2a`;
- candidate IDs: `d259ec1f3cccae2dc0756ce6b318253359970ca759e89fce92d36b5336ca1aa4`;
- exclusion manifest file: `b4aa12fdf1126e11512579c71ce2a38f109aecbdac0081758951c2757f99103a`;
- Node policy decisions: `3f4999ae8d4282f6a71c25fe790ca28cad1fd7549fdb07f17a2bbdd209bbff0b`.

## Clean-replay gates

1. source Stage 1/3/4/6 code is byte-unchanged;
2. empty cache and six official OCP packages;
3. official hashes exact;
4. exact candidate universe, cohort and code exclusions;
5. exact cohort, labels and candidate IDs;
6. exact source-policy decisions and reasons;
7. original independent Node policy implementation PASS on the fresh output;
8. independent Python policy implementation PASS;
9. exact metrics and permutation control;
10. tampered report and cohort rejected.

## Promotion rule

A public PASS closes `stage7_third_cohort_clean_reconstruction`. It does not directly write `1000/1000`; the final G09 contract must ingest the exact Stage 6 and Stage 7 receipts and independently authorize promotion.

## Boundary

The result remains limited to evidence-supported `CONTRACTOR_PAYMENT` attribution in public Honduras ONCAE–SEFIN 2023–2025 data. It does not prove legality, receipt, quality, liquidation, fraud, corruption, causality or global universality.
