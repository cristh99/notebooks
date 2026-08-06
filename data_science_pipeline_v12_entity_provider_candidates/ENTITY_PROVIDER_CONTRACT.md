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
PR #135 single arbiter
```

Lane E cannot emit a canonical entity decision. It cannot rewrite Normalize, use fuzzy similarity, or bypass the single arbiter.

## Frozen input contract

From v4 Normalize, candidate extraction uses the exact word-level lineage already produced upstream:

- `document_id`, `page_id`, deterministic `word_id` / recoverable `line_id`;
- `text_raw` and `token_normalized`;
- `word_num` and OCR bounding box (`left_px`, `top_px`, `width_px`, `height_px`);
- `lineage_parent_sha256`;
- separately bound `source_sha256` and `normalization_manifest_sha256`.

The registry is a separate governed input. Lane E does **not** normalize registry strings. Every record must provide:

- `entity_id`, `canonical_name`, `entity_type`;
- `registry_record_sha256`;
- `alias_tokens_normalized`: one or more already-normalized token sequences; and/or
- `identifier_tokens_normalized`: one or more already-normalized identifier sequences;
- optional `generic_jurisdiction=true`.

A registry sequence that maps exactly to more than one entity fails closed before candidate extraction.

## Matching rule

Only **exact contiguous equality** over upstream `token_normalized` values is permitted.

Explicitly prohibited:

- substring search;
- fuzzy/Levenshtein/Jaro similarity;
- phonetic matching;
- acronym expansion not present in the governed registry;
- ad-hoc normalization in this lane;
- label leakage from evaluation fields.

This intentionally differs from the historical v5 entity resolver, which used `norm(alias) in normalized` over line windows. That path remains historical regression evidence; it is not Lane E's strict identity rule.

## Role support

For v1, role support is deliberately narrow and same-line only:

- supplier: exact cue `proveedor`, `contratista`, or `adjudicatario`;
- buyer: exact cue `comprador` or exact sequence `entidad contratante`.

No cue → contextual candidate only. Multiple incompatible role cues → no body-role support. Generic jurisdiction records always abstain.

## Candidate semantics

Lane E may emit candidate hints only:

- `EXACT_SOURCE_BOUND_ENTITY` — exact governed identifier plus body role support;
- `DOCUMENT_LOCAL_ENTITY_MENTION` — exact governed alias plus body role support;
- `CONTEXTUAL_ORGANIZATION_ONLY` — exact mention without role support;
- `GENERIC_JURISDICTION_ABSTAIN` — jurisdictional context only.

Every candidate binds source/normalization hashes, line/word IDs, character span, bounding box, resolver version, policy hash, registry-row hash, exact match kind and downstream validation requirement.

`registry_support=true` is deliberately stricter than mere registry membership: it is set only for an exact governed identifier match with body-role support and a non-generic entity. This prevents registry presence alone from bypassing the arbiter contract's body-role requirement.

## Evaluation leakage boundary

The existing FOR-ABS supplier benchmark contains authoritative RTN used as ground truth and split control. Its frozen receipt explicitly says `rtn_used_as_feature=false`. Lane E therefore does not consume benchmark RTN labels, `supplier_id_exact`, `supplier_name_exact`, test metrics, or split outcomes as features.

Those artifacts may later evaluate a frozen resolver, but cannot train, tune or generate its candidate identity assertions.

## Public/private boundary

Candidate rows may contain OCR surface text and entity display names in a private technical artifact. Public receipts must use commitments only. `candidate_public_commitment()` hashes document/page/line/entity values and does not export raw names or OCR text.

## Promotion boundary

This implementation is software-only. It proves only deterministic fail-closed candidate construction over supplied inputs. It does not establish external entity-resolution accuracy, provider identity, beneficial ownership, payment, legality, intent, corruption or production readiness.

Next scientific gate: bind Lane V validator evidence and PR #135 arbiter, freeze a fresh preregistered document/registry evaluation, then run without post-result retuning.
