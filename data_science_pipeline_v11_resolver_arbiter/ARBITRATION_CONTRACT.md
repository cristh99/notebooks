# Data Science resolver arbiter v1 — frozen integration contract

**Coordination:** `COORD-2026-08-06-PARALLEL-V2`  
**Status:** `PREREGISTERED_SOFTWARE_INTEGRATION_ONLY`  
**Base authority:** `5707a9e777ca7ee2d216ce6580bab6575dd8b148` (`data_science_pipeline_v10_signed_validator`)  
**External document access:** `0`  
**Production writes:** `0`  
**External spend:** `USD 0.00`

## Purpose

Consolidate the existing Data Science resolver work into one deterministic decision layer without creating another normalizer, reopening exposed documents, retuning rules after outcomes, or allowing two branches to write competing canonical entities, amounts, or dates.

## Existing authorities consumed, not duplicated

- `data_science_pipeline_v4_normalize`: stable document/page/line/word records and hashes.
- `data_science_pipeline_v5_resolve`: bounded entity/date/legal-reference/amount candidate extraction and collision handling.
- `data_science_pipeline_v9_evidence_scope`: provenance, metadata, OCR-content and diagnostic-control separation.
- `data_science_pipeline_v10_signed_validator`: validator registry, policy/channel authorization and signed receipts.

The arbiter is downstream of all four. It may accept, reject, quarantine or abstain; it may not rewrite upstream normalized rows or silently reinterpret their hashes.

## Single-writer topology

```text
normalized records
  ├─ Lane E: entity/provider candidate resolver
  ├─ Lane M: amount/date candidate resolver
  └─ Lane V: provenance/validator evidence
              ↓
        one read-only arbiter
              ↓
  ACCEPT | ABSTAIN | QUARANTINE | REJECT
              ↓
       one hash-bound receipt
```

Only the arbiter may emit a promoted resolution decision. Lanes E, M and V emit candidates and evidence only.

## Canonical input envelope

Every candidate must bind:

```text
document_id
page_id
line_id or word_ids
source_sha256
normalization_manifest_sha256
candidate_type
candidate_value_normalized
candidate_value_display
span_start / span_end
bbox, when present
resolver_id
resolver_version
policy_sha256
evidence_channel
validator_id
validation_receipt_sha256
```

Missing lineage forces `QUARANTINE_MISSING_LINEAGE`; it never becomes a negative or clean result.

## Lane E — entity/provider

Allowed outputs:

- `EXACT_SOURCE_BOUND_ENTITY`
- `DOCUMENT_LOCAL_ENTITY_MENTION`
- `CONTEXTUAL_ORGANIZATION_ONLY`
- `GENERIC_JURISDICTION_ABSTAIN`
- `COLLISION_ABSTAIN`
- `INSUFFICIENT_EVIDENCE`

Promotion requires all of:

1. exact source-bound text or an independently governed registry assertion;
2. role support in document body, not filename or page title alone;
3. no unresolved competing entity with equal or stronger evidence;
4. validator authorized for the exact policy and channel;
5. deterministic replay of the candidate manifest.

Fuzzy similarity can rank review candidates but cannot promote identity by itself.

## Lane M — amount/date

Allowed semantic classes:

- monetary amount;
- calendar date;
- fiscal period;
- legal-instrument identifier;
- telephone/contact token;
- page/list number;
- unresolved numeric token.

Promotion requires class-specific syntax and context. The following must fail closed:

- fiscal year interpreted as currency;
- telephone number interpreted as amount;
- decree number interpreted as date or amount;
- table-of-contents page number interpreted as date;
- amount without currency/role evidence when multiple numeric classes remain plausible;
- date inferred from file metadata when the claim requires document-body support.

## Arbiter precedence

1. integrity and source hash;
2. immutable normalized lineage;
3. evidence-channel authorization;
4. validator signature and registry hash;
5. semantic class constraints;
6. role/context support;
7. collision analysis;
8. acceptance or abstention.

Any failure in 1–4 is `QUARANTINE`. Failures in 5–7 are normally `ABSTAIN` unless evidence is contradictory, in which case `REJECT_CONTRADICTORY`.

## Conflict rules

- Two accepted entities for one exclusive role → `COLLISION_ABSTAIN`.
- Same numeric span classified into incompatible classes → `CLASS_CONFLICT_ABSTAIN`.
- Native-control evidence contradicts OCR candidate → `OCR_CANDIDATE_QUARANTINE`.
- Metadata-only claim presented as body evidence → `CHANNEL_SCOPE_REJECT`.
- Registry hash or signature drift → `VALIDATOR_TRUST_QUARANTINE`.
- Later stronger evidence may supersede a decision only through an append-only successor receipt.

## Required output receipt

```text
coordination_id
arbiter_version
input_manifest_sha256
policy_sha256
validator_registry_sha256
candidate_count_by_lane
accepted_count
abstained_count
quarantined_count
rejected_count
decisions[]
replay_digest
external_cost_usd
production_writes
claim_limit
next_gate
```

The receipt must be byte-identical across two independent executions over the same inputs.

## Frozen acceptance tests

1. exact issuing entity with body role is accepted;
2. address-landmark organization is contextual only;
3. generic `HONDURAS / Gobierno de la República` abstains;
4. equal-strength entity collision abstains;
5. `62-2023` remains a legal instrument, not date/amount;
6. `+504 2209-5355` remains telephone, not amount;
7. `EJERCICIO FISCAL 2024` does not emit `L 2024`;
8. explicit `L. 1,250.00` is a monetary candidate;
9. metadata-only publisher claim cannot become body-supported identity;
10. native-control contradiction quarantines OCR;
11. forged or wrong-validator signature fails closed;
12. unauthorized policy/channel fails closed;
13. altered normalized hash fails closed;
14. non-finite numeric values fail before decision;
15. two executions produce byte-identical receipt;
16. no external network, GCloud, production write or paid service is required.

## Promotion boundary

This contract does not itself prove resolver accuracy, external generalization, beneficial ownership, payment, legality, intent or corruption. A subsequent implementation must pass these frozen tests and then face a fresh preregistered external document gate. Existing exposed documents may be used only for software regression, not promotion credit.

## Ownership

- Arbiter/integration owner: GPT-5.6 Pro until an explicit successor ACK is posted in `cristh99/my_first_repository#153`.
- Existing resolver branches remain evidence inputs; they are not silently merged or declared canonical.
- Any competing arbiter or normalizer created after this freeze must back off or explicitly supersede this contract through the coordination issue.