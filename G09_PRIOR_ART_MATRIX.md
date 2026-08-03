# FIN-RVI-002 G09 — final prior-art boundary and empirical discovery

## Verdict

The **methods are not new**. Record linkage, supplier reconciliation, procurement–spending integration, PO/invoice/vendor matching, documentary audit evidence, one-to-many purchase-to-pay structure, abstention, provenance and costly evidence acquisition all have substantial scholarly, official and patent prior art.

The result that survives is narrower and empirical:

> **FIN-RVI-002-C1.** On an independently sealed public ONCAE–SEFIN cohort of 120 pairs, after exact contract/project-code blocking and compatible supplier identity, `POLICY_DOCUMENTARY_V3` reduced unsupported promotions to `CONTRACTOR_PAYMENT` from **20 to 0** relative to `CODE+SUPPLIER`, while preserving **58/58** supported payments. A clean source reconstruction reproduced the cohort, labels, metrics and hashes.

This is a **domain-bounded original empirical result**, not a claim that the underlying reconciliation techniques are new.

## Evidence chain

| Stage | Role | Result |
|---|---|---|
| Stage 3 | Counterexample-guided development | Baseline: 19 unsafe; documentary v2: 17 unsafe and 56/57 recovery. Claim not passed. |
| Stage 4 | Independent sealed cohort; all 118 Stage 3 codes excluded | Baseline: 20 unsafe, 58/58 recovery. Policy v3: 0 unsafe, 58/58 recovery. Permutation: 21 unsafe, 37/58 recovery. |
| Stage 5 | Clean reconstruction from six official packages | Exact cohort, labels, metrics and logical hashes reproduced by independent Python and Node verifiers. G07 PASS. |

### Pinned public evidence

- Stage 3 run `30840335568`, artifact `8866730681`, report `e12ac82c517ede58cbe2ee1339c24ae6c406251c08e562afd856e65eb859c6f4`.
- Stage 4 run `30841561243`, artifact `8867231467`, report `83e83d5893c7df8ab425debbb21e9edd5eda60e08309cfbd4905bd84a5ffbc7d`.
- Stage 5 run `30844453922`, artifact `8868335548`, reconstructed report `e825184bc0e4389e8475b9a861d852b40c39b57322cbad574b4d4880fc67f811`.
- Stage 5 Python receipt `03e97d0eb13ad7808a1a78f37ff2e8d16695ca092ccf3ed76f7cd12a78b795be`.
- Stage 5 Node receipt `3fa82f11d111d97e3b5fcaf58680a413f1482e01744e336cd5e64fa0c33d72d6`.

## Prior-art matrix

| Component | Primary prior art | Disposition |
|---|---|---|
| Public-payment record linkage | Rahal, *The Keys to Unlocking Public Payments Data*, DOI `10.1111/kykl.12171` | **ABSORBED** |
| Supplier-name reconciliation | *The CORFU technique*, DOI `10.1016/j.csi.2015.02.009` | **ABSORBED** |
| Procurement + spending knowledge graphs | *Data Quality Barriers for Transparency in Public Procurement*, DOI `10.3390/info13020099` | **ABSORBED** |
| Global procurement data integration | GPPD, DOI `10.1016/j.dib.2024.110412`; FOPPA, DOI `10.1038/s41597-023-02213-z` | **ABSORBED** |
| Procurement-object similarity | *Matchmaking Public Procurement Linked Open Data*, DOI `10.1007/978-3-319-26148-5_27` | **ABSORBED** |
| Many-to-many purchase-to-pay structure | *Analyzing Inter-Connected Processes*, DOI `10.21203/rs.3.rs-2872013/v1` | **ABSORBED** |
| Open-set document rejection | *Supplier qualification document recognition through open-set recognition*, DOI `10.1109/DSAA60987.2023.10302610` | **ABSORBED** |
| Procurement red flags and false-positive management | IDB, DOI `10.18235/0004595` | **ABSORBED** |
| Documentary and physical audit evidence | INTOSAI GUID 5280 | **ABSORBED** |
| Adaptive costly evidence | Adaptive submodularity, noisy active learning and costly information acquisition | **ABSORBED** |
| Contract/invoice/vendor reconciliation | Patents `US8494935B2`, `US7865411B2`, `US20060095373A1`, `US12243082B1`, `US8930295B2` | **ABSORBED** |
| Honduras ONCAE–SEFIN integration | World Bank Honduras CPAR and OCP Honduras portal implementation | **ABSORBED** |
| Exact sealed safety–recovery result | No located primary source reports the exact ONCAE–SEFIN baseline/challenger comparison and reproduced result above | **ORIGINAL EMPIRICAL RESULT UNDER BOUNDED SEARCH** |

## Search protocol

The search log records the date, exact queries, engines, inclusion rules, deduplication, saturation rule, source decisions and limitations. It used:

- Exa;
- SciSpace;
- Scholar Sidekick citation verification;
- Parallel Search;
- Consensus results obtained before its monthly limit was exhausted;
- official standards and reports;
- patent search;
- Spanish and Honduras-specific queries.

Elicit and Scite were unavailable under the connected plans; those failures are explicit. The search is bounded and the novelty decision is revocable if an earlier exact source is later found.

## Why the claim is distinct

The closest work supplies individual ingredients, but none located simultaneously reports:

1. public ONCAE and SEFIN source packages;
2. exact code plus compatible supplier as the strong baseline;
3. object/document evidence as the challenger;
4. one-to-many contract–financial-event cardinality;
5. fail-closed abstention;
6. unsafe promotion and supported-payment recovery as paired decision metrics;
7. monetary amount at risk;
8. a development cohort, disjoint sealed cohort, permutation control and clean cross-language reconstruction;
9. the observed `20 → 0` safety improvement with `58/58` recovery.

## Scope and revocability

`PASS` means only that the exact empirical claim survived the declared bounded search and replication gates as of **2026-08-03**. It does not establish novelty of record linkage or procurement reconciliation generally, nor legality, delivery, quality, liquidation, fraud, corruption or physical result.

```text
G07 = PASS
G09 = PASS — DOMAIN-BOUNDED ORIGINAL EMPIRICAL RESULT
FINANCE_SCORE = 1000/1000
```
