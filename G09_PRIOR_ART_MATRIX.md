# FIN-RVI-002 G09 — prior-art matrix and claim boundary

## Verdict

The broad ideas are **not new**: procurement entity reconciliation, procurement–spending integration, document provenance, costly evidence acquisition, adaptive testing, abstention under insufficient evidence, and preservation of source lineage all have substantial prior art.

The only defensible research candidate is a **specific empirical claim** about maximum permissible financial attribution on Honduras ONCAE–SEFIN data. It remains `OPEN` until Stage 2, a clean reconstruction, and an independent cross-cohort replication all pass.

## Candidate claim

> **FIN-RVI-002-C1.** On a sealed public ONCAE–SEFIN holdout, after exact contract/project-code blocking and compatible supplier identity, object/document evidence strictly reduces unsupported promotions to `CONTRACTOR_PAYMENT` relative to the strong `CODE+SUPPLIER` baseline, without reducing supported-payment recovery, when one-to-many contract–financial-event cardinality and fail-closed abstention are preserved.

This is an empirical, domain-bounded claim. It is **not** a claim that record linkage, active information acquisition, provenance, or procurement knowledge graphs are new.

## Primary prior-art matrix

| Component | Primary prior art | What is already known | Status for FIN-RVI-002 |
|---|---|---|---|
| Public-payment record linkage | Charles Rahal, *The Keys to Unlocking Public Payments Data*, Kyklos 2018, DOI `10.1111/kykl.12171` | Large-scale public payments can be cleaned and linked to institutional registers using targeted, domain-specific reconciliation; false positives require evaluation. | **ABSORBED** |
| Procurement supplier-name reconciliation | Álvarez-Rodríguez, Vafopoulos & Lloréns, *The CORFU technique*, Computer Standards & Interfaces 2015, DOI `10.1016/j.csi.2015.02.009` | Stepwise NLP/semantic unification of heterogeneous corporate names in procurement, evaluated with precision and recall. | **ABSORBED** |
| Procurement + company + spending integration | Soylu et al., *Data Quality Barriers for Transparency in Public Procurement*, Information 2022, DOI `10.3390/info13020099` | Procurement, company and spending data can be integrated in a knowledge graph; missing identifiers and broken lifecycle links materially limit analytics. | **ABSORBED** |
| Contract lifecycle, transactions and documents | Open Contracting Data Standard, World Bank/OCP | Procurement should link planning, tender, award, contract, implementation, transactions and official documents; unique identifiers and source documents are central. | **ABSORBED** |
| Adaptive costly information acquisition | Golovin & Krause, *Adaptive Submodularity*, JAIR 2011 / arXiv `1003.3967` | Under adaptive-submodular structure, greedy acquisition can be near-optimal; arbitrary adaptive information gathering is hard. | **ABSORBED** |
| Noisy expensive tests and decision-equivalence classes | Golovin, Krause & Ray, *Near-Optimal Bayesian Active Learning with Noisy Observations*, NeurIPS 2010 | Expensive tests can be selected adaptively to distinguish decision-relevant equivalence classes; common greedy criteria can fail. | **ABSORBED** |
| Non-myopic value of information | Krause & Guestrin and subsequent work | Cost-aware, non-myopic observation selection and value-of-information optimization are established research areas. | **ABSORBED** |
| Evidence acquisition mechanisms | *Sequential Mechanisms for Evidence Acquisition* and earlier evidence/information-acquisition literature | Sequential, threshold-structured acquisition of costly evidence is established. | **ABSORBED** |
| Provenance, evidence links and refutation | Friedman et al., *Provenance-Based Interpretation of Multi-Agent Information Analysis*, TaPP 2020 | Provenance graphs can preserve evidence, appraisals, assumptions, derivations and counterfactual refutation. | **ABSORBED** |
| One-to-many lifecycle cardinality | OCDS and procurement ontologies | Processes, awards, contracts, implementation events and transactions have distinct grains and nontrivial cardinalities. | **ABSORBED AS DATA MODELING** |
| Maximum permissible claim ladder | No exact primary source found that operationalizes `PROJECT_RELATED → CONTRACT_ATTRIBUTED → CONTRACTOR_PAYMENT → RECEIPT → ASSET_OR_SERVICE → RESULT` for cross-source procurement–payment linkage. | Related work distinguishes entities, contracts, payments, implementation and results, but the explicit fail-closed promotion ladder was not found as an evaluated linkage protocol. | **COMBINATION CANDIDATE** |
| Monetary amount-at-risk from false promotion | Record-linkage work evaluates accuracy; public-finance work evaluates money flows. No exact protocol found that scores unsupported promotion by the affected payment amount while preserving abstention. | Cost-sensitive classification is general prior art; this exact domain metric is not yet established as novel. | **COMBINATION CANDIDATE** |
| Proof-carrying semantic replay | Provenance and reproducibility are established; proof-carrying computation is established in other domains. | No exact prior source found for byte-bound Python/Node replay of a procurement–payment claim ladder and its gate score. | **COMBINATION CANDIDATE** |
| Honduras ONCAE–SEFIN result after strong blocking | No located primary study evaluates exact-code + supplier baseline against object/document evidence on the 2023–2025 public ONCAE–SEFIN corpus. | Absence from this search is not proof of novelty. | **EMPIRICAL CANDIDATE** |

## Exclusive predictions

The candidate claim survives only if every prediction below holds on a sealed cohort not used to create the policy:

1. `unsafe(POLICY_DOCUMENTARY) < unsafe(B1_CODE_SUPPLIER)`.
2. `supported_recovered(POLICY_DOCUMENTARY) >= supported_recovered(B1_CODE_SUPPLIER)`.
3. A fixed permutation of documentary decisions performs worse than candidate-specific documentary evidence.
4. The result is reproduced from official source packages in a clean environment with identical holdout IDs and decision hashes.
5. The direction persists in a second cohort or a separately frozen family/period, not only in one handpicked collection.
6. No promoted row violates the maximum permissible claim supported by its evidence.

## Falsifiers

Any one of these closes the current claim as false or underspecified:

- `CODE+SUPPLIER` matches documentary safety and supported recovery;
- documentary evidence merely adds abstention but loses supported payments without a declared utility advantage;
- the permutation control performs equally well;
- the effect vanishes after preserving one-to-many event cardinality;
- the clean replay changes holdout membership or decisions;
- a prior primary publication already reports the same protocol and result;
- the effect exists only in a single code family and fails the replication cohort.

## Required evidence for G09 PASS

1. Stage 2 strong-baseline result passes every preregistered check.
2. Clean independent source reconstruction reproduces hashes and metrics.
3. A second sealed cohort reproduces direction and safety.
4. A systematic primary-source search log records queries, databases, dates and inclusion decisions.
5. The final claim is stated no more broadly than the evidence.

Until then:

```text
G09 = OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED
```
