# FIN-RVI-002 — prior-art boundary and residual claim

## Verdict

The broad claim is **not novel**. Sequential entity resolution, cost-aware action selection, active acquisition of external evidence, gradual disclosure, abstention, provenance-aware governance, relation-aware matching, procurement entity reconciliation, public-payment linkage, and many-to-many purchase-to-pay modeling all have substantial prior art.

FIN-RVI-002 therefore does **not** claim invention of any of those components. The only defensible candidate contribution is their narrow, proof-carrying empirical composition for cross-system public-finance claims, evaluated by unsupported monetary attribution rather than ordinary pairwise F1.

## Prior-art matrix

| Prior work | What it already establishes | Consequence for FIN-RVI-002 |
|---|---|---|
| Tahamont et al., *No Ground Truth? No Problem* (NBER 31100, 2023) | Active learning can tactically request high-value labels for administrative-data linkage and obtain most achievable gains with limited ground truth. | No claim that selective evidence/labels for administrative linkage are new. |
| Rohde et al., *Multi-Layer Privacy-Preserving Record Linkage with Clerical Review based on gradual information disclosure* (BTW 2025; arXiv:2412.04178) | Uncertain pairs can progress through evidence layers, revealing additional attributes only when needed. | No claim that staged evidence acquisition or gradual disclosure is new. |
| Papadakis et al., *Agentic ER: The next frontier in Entity Resolution* (arXiv:2607.27435, 2026) | Frames ER as sequential decision-making with adaptive external evidence acquisition and accuracy–cost–latency trade-offs. | Absorbs the broad “agent chooses what evidence to obtain next” claim. |
| Wang et al., *CaRL-EM: Cost-Aware Reinforcement Learning for Entity Matching with LLMs* (ACL 2026) | Learns a sequential controller over matching operators and termination under explicit cost. | No claim that cost-aware sequential matching control is new. |
| Wang et al., *Match, Compare, or Select?* (COLING 2025) | Demonstrates that global candidate interactions and selection can outperform isolated binary matching. | No claim that pairwise-independent matching is generally sufficient or that listwise comparison is new. |
| *Disambiguate Entity Matching using LLMs through Relation Discovery* (GUIDE/ACM 2024; arXiv:2403.17344) | Replaces a single binary “match” with task-specific relation types and human-controlled downstream use. | Absorbs the broad idea that relation semantics must precede high-stakes consumption. |
| Galán-Mena et al., *OntoDup* (Information, 2026; DOI 10.3390/info17040325) | Represents matches as governed assertions with evidence, provenance, lifecycle status, conflict handling and controlled materialization. | No claim that auditable assertions, abstention queues, or policy-controlled promotion are new. |
| Herschel et al., *Provenance for Entity Resolution* | Defines and captures processing provenance for entity-resolution pipelines. | No claim that ER provenance is new. |
| Berti et al., *Analyzing interconnected processes* (IJDSA, 2023; DOI 10.1007/s41060-023-00427-3) | Purchase-to-pay processes contain many-to-many order–invoice–payment relations; forcing a single case notion creates convergence/divergence and misleading analytics. | No claim that P2P cardinality problems are new. It supports preserving one-to-many contract/payment relations. |
| Rahal, *The Keys to Unlocking Public Payments Data* (Kyklos, 2018; DOI 10.1111/kykl.12171) | Scrapes, cleans and links tens of millions of public-payment records to institutional registers under heterogeneous identifiers. | No claim that public-payment record linkage is new. |
| Álvarez-Rodríguez et al., CORFU (Computer Standards & Interfaces, 2015; DOI 10.1016/j.csi.2015.02.009) | Reconciles corporate names in public-procurement data. | No claim that procurement supplier-name reconciliation is new. |
| Soylu et al., *Data Quality Barriers for Transparency in Public Procurement* (Information, 2022; DOI 10.3390/info13020099) | Documents missing identifiers, heterogeneous procurement data and the need for entity reconciliation. | No claim that procurement interoperability problems are new. |
| Avogadro et al., *Building a Canonical Register of Public Sector Entities* (ISWC 2025 Companion) | Hybrid LLM/KG procurement entity linking at scale, evaluated on 1,000 manually curated entries. | No claim that procurement entity linking or contextual validation is new. |
| Kim & Giles, *Financial Entity Record Linkage with Random Forests* (2016; DOI 10.1145/2951894.2951908) | Financial-database entity linkage using exact rules plus learned comparison. | No claim that financial entity record linkage is new. |

## Residual candidate claim

The searched literature did not reveal an exact prior instance of the following combined claim:

> In cross-system public-finance reconciliation, a shared contract/project code establishes only a candidate relation. A contractor-payment claim must preserve real one-to-many cardinality and pass a typed evidence ladder requiring compatible institutional identity, supplier identity, financial object and document provenance; otherwise the system must abstain. The operational value is measured as unsupported monetary attribution avoided on a pre-frozen official-data holdout, with deterministic replay.

This candidate has four narrow components:

1. **Claim-level semantics, not only entity identity**
   - `PROJECT_RELATED`
   - `CONTRACT_ATTRIBUTED`
   - `CONTRACTOR_PAYMENT`
   - `RECEIPT`
   - `ASSET_OR_SERVICE`
   - `RESULT`

   Evidence sufficient for an earlier level never silently promotes a later level.

2. **Cardinality-preserving procurement-to-payment reconciliation**

   A contract or project may correspond to several advances, estimates, reversals, retentions, taxes or auxiliary expenses. Amount equality and one-to-one matching are not valid universal assumptions.

3. **Fail-closed monetary utility**

   The principal loss is not merely a false-positive pair. It is the amount and downstream claim wrongly attributed to a contractor, contract, physical delivery or result.

4. **Proof-carrying prospective evaluation**

   Candidate selection is frozen before supplier/object adjudication; source packages, documents, decisions and replay are hash-bound.

## Stage 1 evidence

Using official OCP Registry packages for Honduras ONCAE and SEFIN, 2023–2025:

- 454,542 releases reconstructed with zero parse errors;
- 2,295 code-linked candidates;
- frozen holdout: 20 pairs, including 16 non-one-to-one relations;
- baseline promotes all 20 as contractor payments;
- evidence policy returns 16 `SUPPORTED`, 1 `REJECTED`, 3 `UNRESOLVED`;
- baseline unsupported promotions: 4/20 = 20%;
- evidence-policy unsupported promotions: 0;
- unsupported amount at risk avoided: L 4,644,050.40;
- 20/20 public documents acquired;
- deterministic replay SHA-256: `0441d92dfa643e93ee95c77955ce6d24e09f343a0bf9572966299d56d0bef826`.

## What remains before G09 PASS

1. Independent clean replay of the full experiment.
2. Independent adjudication or external ground truth for the 20 holdout pairs.
3. A broader holdout spanning SIT, FHIS, ENP and municipal cases.
4. Direct comparison against relation-aware, governance-aware and agentic ER baselines where implementable.
5. A systematic-review search protocol with databases, queries, dates and exclusion reasons.
6. Evidence that the claim ladder and monetary-loss metric change real audit or acquisition decisions beyond one jurisdiction.
7. Exact statement of scope: public procurement-to-financial-event reconciliation, not general entity resolution.

## Falsifiers

The residual claim fails if any of the following occurs:

- a simple baseline attains the same unsupported-promotion rate and monetary utility at lower cost;
- supplier/object/document evidence does not alter decisions beyond shared code;
- preserved cardinality adds no predictive or operational value;
- independent adjudication overturns the automated `SUPPORTED/REJECTED/UNRESOLVED` pattern;
- benefit disappears outside one institution or code family;
- the literature contains the same claim ladder, monetary utility and prospective proof-carrying evaluation.

## References

- https://www.nber.org/papers/w31100
- https://arxiv.org/abs/2412.04178
- https://arxiv.org/abs/2607.27435
- https://aclanthology.org/2026.acl-long.1258/
- https://aclanthology.org/2025.coling-main.8/
- https://arxiv.org/abs/2403.17344
- https://doi.org/10.3390/info17040325
- https://doi.org/10.1007/s41060-023-00427-3
- https://doi.org/10.1111/kykl.12171
- https://doi.org/10.1016/j.csi.2015.02.009
- https://doi.org/10.3390/info13020099
- https://ceur-ws.org/Vol-4085/paper2.pdf
- https://doi.org/10.1145/2951894.2951908
