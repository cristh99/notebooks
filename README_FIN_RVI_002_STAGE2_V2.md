# FIN-RVI-002 Stage 2 v2 — evidence ladder under strong baselines

Logic Power Problem Solver is used here as a **meta-controller**, not embedded in a financial model. Its canonical route classified Finance 1000/1000 as an active-information, decision, planning, and verification problem; `robust_minimax_regret` selected the next action: close G07 with a strong-baseline evidence ladder and public clean replay while G09 proceeds separately.

## Starting state

- canonical Finance score: `820/1000`;
- `G07 = OPEN` — deployed economic/institutional utility not yet certified;
- `G09 = OPEN` — novel, falsifiable, prior-art-delimited and independently replicated discovery not yet certified.

Stage 2 v1 passed CI but was non-evaluable: its random holdout did not intersect the pre-existing adversarial gold. V2 treats that zero-overlap as an obstruction, not as a success.

## Frozen corpus

`frozen_adjudication_corpus_v2.json` contains 42 public ONCAE–SEFIN candidate pairs derived from artifacts that existed before this policy evaluation:

- Stage 0 cases and report;
- Stage 1 `known_target_hits.json`;
- pre-existing Notion adjudications for SIT, FHIS and ENP cases.

The policy receives only evidence fields. It cannot read `gold_expected`, `gold_rule`, `split`, or `source_url`. A SHA-256 split creates `DEVELOPMENT` and `SEALED_TEST` partitions.

## Competing policies

1. `B0_CODE` — shared contract/project code.
2. `B1_CODE_SUPPLIER` — code plus compatible payee identity.
3. `B2_CODE_SUPPLIER_AMOUNT` — B1 plus amount difference ≤5%.
4. `B3_DOCUMENTARY` — Stage 1 supplier/object adjudication.
5. `EVIDENCE_LADDER` — payment nature, payee authority, object compatibility, chronology, and allocation/cardinality must all support the maximum claim.

The ladder fails closed on auxiliary expenditure, reversals, reservation-only records, consortium/member ambiguity, untyped source-date conflicts, multi-project allocation, and insufficient object evidence.

## Promotion gate

G07 becomes a candidate pass only when all preregistered checks pass:

- development and sealed sets contain positive and nonpositive cases;
- zero unsafe promotions in both;
- all supported cases recovered;
- strictly fewer unsafe promotions than code+supplier;
- higher sealed binary accuracy than code+supplier;
- strict dominance over every declared baseline on the full corpus;
- deterministic rotated-evidence negative control is worse;
- Stage 1 public-document acquisition succeeded for the full shadow holdout;
- Python and an independent Node implementation agree;
- tampered report and corpus controls fail.

A public clean replay upgrades the candidate from `820` to **`920/1000`** by closing G07. G09 remains worth 80 points and stays open.

## Reproduce

```bash
python -m compileall -q fin_rvi_002_stage2
python -m unittest discover -v -s fin_rvi_002_stage2 -p 'test_stage2_v2.py'
python -m fin_rvi_002_stage2.run_stage2_v2
node fin_rvi_002_stage2/verify_stage2_v2.mjs
```

## Boundary

The experiment tests the maximum permissible claim `CONTRACTOR_PAYMENT`. It does not prove legality, physical receipt, quality, liquidation, fraud, corruption, or final public outcome. The random Stage 1 cohort remains a shadow deployment without independent labels.
