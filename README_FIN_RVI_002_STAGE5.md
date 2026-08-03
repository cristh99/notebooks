# FIN-RVI-002 Stage 5 — clean reconstruction of G07

Logic Power Problem Solver selected `parallel_g07_g09_program` at a canonical Finance score of `820/1000`. Stage 5 executes the remaining G07 operation: reconstruct the successful Stage 4 policy on a fresh public runner from the official ONCAE and SEFIN packages, then verify it independently in Python and Node.

## Frozen source

- Stage 4 source head: `9e6686204fce20bc21d17f041d506a2a9c92761d`;
- Stage 4 public run: `30841561243` — SUCCESS;
- Stage 4 artifact: `8867231467`;
- artifact SHA-256: `a1a4a2e7dd3a722ce9b1dac9b5dbe02a5bfde0f7bd63c9e5fb6974c056de3928`.

This branch may add only the Stage 5 verification capsule. CI proves that `fin_rvi_002_stage1`, `fin_rvi_002_stage3`, and `fin_rvi_002_stage4` are unchanged from the frozen source.

## Reconstruction gates

1. fresh empty cache;
2. six official OCP Registry source packages with fixed SHA-256;
3. candidate universe `2,295`;
4. exact new cohort of `120`, excluding all `118` Stage 3 codes;
5. no shared code represented more than twice;
6. labels `58 SUPPORTED / 28 REJECTED / 34 UNRESOLVED`;
7. strong baseline: `20` unsafe promotions and `58/58` recovery;
8. documentary policy v3: `0` unsafe promotions and `58/58` recovery;
9. deterministic permutation control: `21` unsafe and `37` recovered;
10. exact file and logical hashes for cohort and labels;
11. original Stage 4 Node verifier PASS;
12. new independent Python and Node receipts agree;
13. tampered-row controls rejected.

## Promotion

A full public PASS closes `G07` and promotes Finance from **820/1000 to 920/1000**. `G09` remains open at 0/80 pending the bounded claim’s prior-art and scientific replication gates.

## Boundary

The result is evidence for the maximum claim `CONTRACTOR_PAYMENT` in the declared Honduras ONCAE–SEFIN cohorts. It does not prove legality, physical receipt, quality, liquidation, fraud, corruption, or final public outcome.
