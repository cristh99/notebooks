# Finance Power v1 — Logic Power v10 applied to financial decisions

Finance Power v1 compiles finite financial decisions into the verified
proof-carrying active-discovery engine in Logic Power v10.

## Decision contract

A case declares:

1. a finite set of financial worlds;
2. an exact binary decision property for every world;
3. admissible evidence acquisitions and their rational costs;
4. a rational prior over worlds.

The compiler returns exactly one of:

- an exact adaptive evidence policy that decides the property; or
- an exact obstruction: two worlds with opposite decisions that remain
  indistinguishable under every admissible evidence source.

It never converts missing evidence into confidence.

## Generic compiler

`finance_power_v1.finite_decision` provides:

- `FinancialWorld`;
- `EvidenceAcquisition`;
- `compile_financial_decision`.

Domain adapters are declarations over this common contract. They do not
reimplement the Logic Power v10 solver or certificate protocol.

## Five executed domains

| Domain | Exact fixed basis cost | Optimal worst cost | Optimal expected cost |
| --- | ---: | ---: | ---: |
| Capital allocation | 5 | 5 | 21/5 |
| Credit underwriting | 5 | 5 | 7/2 |
| Liquidity intervention | 3 | 3 | 9/4 |
| Insurance reserve | 4 | 4 | 7/2 |
| Portfolio hedge | 3 | 3 | 2 |

Every domain has:

- an exact case whose evidence grammar separates every opposite decision;
- an impossible control that removes a required decision dimension;
- an `Exact` certificate;
- an `Impossible` certificate with an indistinguishable opposite pair;
- semantic replay and deterministic hashing.

## Capital-allocation reference case

Eight worlds combine:

- strong or weak demand;
- controlled CAPEX or overrun;
- cheap or expensive funding.

The decision is `NPV > 0`, calculated with exact rational arithmetic.
Logic Power v10 finds:

- minimum fixed evidence basis:
  `binding_term_sheet + pilot_and_bid`;
- exact basis cost: `5`;
- optimal adaptive worst cost: `5`;
- optimal adaptive expected cost: `21/5`;
- first action: `pilot_and_bid`.

Removing every demand-sensitive acquisition produces `IMPOSSIBLE` with the
pair `strong__controlled__expensive` and
`weak__controlled__expensive`.

## Reproduce

```bash
python -m unittest finance_power_v1.test_finance_power_v1
python -m finance_power_v1.run --output reports/finance_power_v1.json
```

## Gates

- 10 deterministic unit and adversarial tests;
- exact rational financial arithmetic where used;
- generic finite-decision compilation;
- exact fixed-basis optimization;
- exact adaptive policy synthesis;
- five constructive impossibility witnesses;
- deterministic SHA-256 report;
- Logic Power v10 semantic certificate replay;
- tamper rejection;
- deterministic rebuild.

## Boundary

The result is exact only inside each declared finite world and evidence
language. Real financial use still requires defensible scenario construction,
source provenance, current data, model-risk controls, temporal and stochastic
extensions where needed, and explicit expansion of the evidence grammar when
the monitor returns `UNKNOWN` or `IMPOSSIBLE`.
