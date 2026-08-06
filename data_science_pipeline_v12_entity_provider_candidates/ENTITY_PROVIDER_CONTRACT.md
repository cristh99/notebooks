# Data Science Lane E — entity/provider candidate contract v1

**Coordination:** `COORD-2026-08-06-PARALLEL-V2`  
**Owner:** Mozo 4  
**Status:** `SOFTWARE_ONLY_CANDIDATE_LANE`  
**Base:** `543de7607f689ed424578af3ae0f6fe2c71552ce`  
**External document access:** `0`  
**Production writes:** `0`  
**External spend:** `USD 0.00`

## Position in the pipeline

```text
v4 Normalize words/lines
        +
pre-normalized governed entity registry
        ↓
Lane E exact candidates only
        ↓
Lane V validator/trust evidence
        ↓
Notion-governed single arbiter pointer
```

Lane E cannot emit a canonical entity decision. It cannot rewrite Normalize, use fuzzy similarity, or bypass the single arbiter.

## Frozen input contract

From v4 Normalize, candidate extraction uses the existing word-level lineage:

- `document_id`, `page_id`, deterministic `word_id` / recoverable `line_id`;
- `text_raw` and `token_normalized`;
- `word_num` and OCR bounding box;
- `lineage_parent_sha256`;
- separately bound `source_sha256` and `normalization_manifest_sha256`.

Before matching, Lane E fails closed unless every word satisfies the v4 identity relationships:

- `document_id == sha256:<source_sha256>`;
- `page_id` is a child of that `document_id`;
- `word_id` is a child of the recovered/provided `line_id` and its `:wN` suffix equals `word_num`;
- `word_id` values are unique;
- `lineage_parent_sha256` is a valid lowercase SHA-256;
- bbox coordinates are non-negative and dimensions are positive.

Matched-word lineage hashes are included in the private candidate commitment. The public projection exposes only their manifest hash.

The registry is a separate governed input. Lane E does **not** normalize registry strings. Every row supplies `entity_id`, `canonical_name`, `entity_type`, `registry_record_sha256`, and one or more already-normalized alias or identifier token sequences. A sequence that maps to multiple entity IDs fails closed.

## Matching rule

Only **exact contiguous equality** over upstream `token_normalized` values is permitted. Substring, fuzzy/Levenshtein/Jaro, phonetic, acronym expansion and ad-hoc normalization are prohibited.

This intentionally differs from historical v5 entity logic, which used `norm(alias) in normalized` over line windows. That code remains regression history; it is not Lane E's strict identity rule.

## Role support

Role support is deliberately narrow:

- supplier: exact cue `proveedor`, `contratista`, or `adjudicatario`;
- buyer: exact cue `comprador` or exact sequence `entidad contratante`.

The cue must be on the **same OCR line, outside the matched entity/identifier span, and at most 3 normalized-token positions away**. A role word inside a company name does not count as role evidence. Multiple incompatible nearby role cues force contextual-only treatment. Generic jurisdiction records always abstain.

## Candidate semantics

Lane E may emit hints only:

- `EXACT_SOURCE_BOUND_ENTITY` — exact governed identifier plus body-role support;
- `DOCUMENT_LOCAL_ENTITY_MENTION` — exact governed alias plus body-role support;
- `CONTEXTUAL_ORGANIZATION_ONLY` — exact mention without role support;
- `GENERIC_JURISDICTION_ABSTAIN` — jurisdictional context only.

Every candidate binds source/normalization hashes, per-word lineage hashes, line/word IDs, exact reconstructed character span, bbox, resolver version, policy hash, registry-row hash, match kind and downstream validation requirement.

`registry_support=true` is stricter than mere registry membership: exact identifier + non-generic entity + valid nearby body-role support are all required. Alias and identifier sequences that are identical for the same entity emit one candidate, with identifier evidence taking precedence.

## Evaluation leakage boundary

The existing FOR-ABS supplier benchmark freezes authoritative RTN as ground truth and split control and explicitly states `rtn_used_as_feature=false`. Lane E therefore does not consume benchmark RTN labels, `supplier_id_exact`, `supplier_name_exact`, split outcomes or test metrics as features.

Those artifacts may later evaluate a frozen resolver, but cannot train, tune or generate candidate identity assertions.

## Public/private boundary

Candidate rows may contain OCR surface text and entity display names in a private technical artifact. Public receipts must use commitments only. The commitment projection hashes document/page/line/entity values and word-lineage manifests and does not export raw names or OCR text.

## Validator/arbiter boundary

Lane E intentionally does not forge or synthesize validator evidence. Lane V must attach an authorized signed validation to the exact observation/policy/channel before the Notion-governed arbiter can decide anything. Lane E does not patch either arbiter branch.

At the 2026-08-06 15:59 Honduras coordination cut, Notion still names draft PR `#135` as the single arbiter. A newer GitHub draft `#138` exists as a **technical successor** that states it consumes canonical Lane E/Lane M receipts without numeric reclassification, but that succession is not yet authoritative until its owner reconciles it in Notion.

## Technical compatibility with draft #138

The public `#138` contract requires, among other things, exact event-universe equality, per-event source-record SHA-256 equality, trust/self-hash validation and a final event envelope containing `event_id`, `process_id`, `buyer_id`, `supplier_id`, date/amount/currency, event/amount/date roles, procurement method, bid count, resolution state and lineage.

Lane E v1 deliberately does **not** manufacture that event envelope. Its current output is document/OCR-line candidate evidence and commitments. It does not have an authoritative `event_id/process_id` binding or the amount/date half of the event. Therefore a direct Lane E→`#138` adapter is **BLOCKED_MISSING_EVENT_BINDING**, not an invitation to infer or synthesize missing event fields.

A compatible downstream assembler must bind Lane E candidates plus Lane M candidates to an already governed event universe and source-record hashes, then attach Lane V trust evidence. That assembler belongs to the single arbiter/integration owner, not Lane E.

## Promotion boundary

Software-only candidate construction. It does not establish external entity-resolution accuracy, provider identity, beneficial ownership, payment, legality, intent, corruption or production readiness.

Next gate for Lane E: exact-byte regression execution. After that, remain blocked on authorized Lane V/event-universe binding and the Notion-governed single arbiter; only then may a fresh preregistered document/registry evaluation proceed without post-result retuning.
