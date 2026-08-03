# FIN-RVI-002 Stage 4 — independent validation of policy v3

Logic Power Problem Solver selected counterexample-guided refinement after Stage 3:

- all 17 unsafe documentary promotions had incompatible non-empty supplier RTN/TID values;
- the only missed supported payment had exact numeric supplier identity, payment language, exact code and specific shared object terms.

## Policy fixed before Stage 4

`FIN-RVI-002-DOCUMENTARY-V3`:

1. numeric supplier-identifier conflict is a hard veto;
2. exact numeric identity + payment language + non-conflicting object support can promote;
3. name-only identity requires much stronger object evidence;
4. insufficient evidence remains `UNRESOLVED`.

## Independent cohort

- all 118 shared codes from Stage 3 are excluded;
- Stage 1 holdout and known adversarial codes remain excluded;
- a new 120-row cohort is frozen with a new SHA-256 seed;
- selection uses only family, cardinality, amount bucket and time bucket;
- the conservative Stage 3 evidence labeler is unchanged;
- documents are acquired and extracted after freezing.

## Gate

G07 receives only `PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION` when policy v3 has:

- at least 20 supported and 5 rejected labels;
- zero unsafe promotions;
- strictly fewer unsafe promotions than `CODE+SUPPLIER`;
- no lower supported recovery;
- a worse fixed permutation control;
- Python and Node semantic agreement.

Otherwise G07 remains `OPEN` with the exact failed conditions.
