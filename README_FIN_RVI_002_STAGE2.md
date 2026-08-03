# FIN-RVI-002 Stage 2 — strong-baseline documentary utility test

Stage 2 executes the next action selected by Logic Power Problem Solver v1 for **G07**.

## Question

Does documentary object evidence improve decisions beyond a shared contract/project code **and compatible supplier identity**?

## Sealed input

- Stage 1 public holdout, frozen before supplier/object inspection;
- 20 ONCAE–SEFIN pairs;
- fixed adversarial gold rules created from previously documented cases;
- no post-outcome exclusions.

## Policies

| Policy | Evidence used |
|---|---|
| `B0_CODE` | shared contract/project code |
| `B1_CODE_SUPPLIER` | code + compatible supplier identity |
| `B2_CODE_SUPPLIER_AMOUNT` | B1 + amount difference ≤5% |
| `POLICY_DOCUMENTARY` | B1 + compatible object/classification evidence |

## Primary comparison

Policies are ordered lexicographically:

1. minimize unsafe promotions against frozen adversarial gold;
2. maximize recovered supported cases;
3. minimize missed supported cases;
4. minimize evidence fields used.

No arbitrary utility conversion can compensate for an unsafe financial attribution.

## Negative control

The documentary decisions are rotated across candidate IDs under a fixed seed. Candidate-specific evidence must outperform this permutation on exact agreement or safety.

## Candidate G07 gate

`PASS_CANDIDATE` requires:

- at least one positive and one non-positive gold case evaluated;
- zero documentary unsafe promotions;
- documentary evidence strictly reduces unsafe promotions versus `B1_CODE_SUPPLIER`;
- documentary evidence recovers no fewer supported cases than B1;
- the fixed negative control performs worse;
- Python and Node semantic verifiers agree.

This remains a candidate pass until a clean independent data reconstruction reproduces the same input, decisions and hashes.
