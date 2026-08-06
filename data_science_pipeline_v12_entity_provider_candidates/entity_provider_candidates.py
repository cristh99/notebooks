"""Fail-closed Lane E entity/provider candidate extraction.

Upstream of the single resolver arbiter. This module does not normalize OCR,
write canonical entities, use fuzzy similarity, or consume evaluation labels as
features. It compares only already-normalized OCR word tokens against governed,
pre-normalized registry sequences.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

COORDINATION_ID = "COORD-2026-08-06-PARALLEL-V2"
RESOLVER_ID = "DATA-SCIENCE-LANE-E-ENTITY-PROVIDER"
RESOLVER_VERSION = "V1-20260806"
SCHEMA = "data-science-pipeline/entity-provider-candidates/1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[a-z0-9]+$")

ROLE_SEQUENCES: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "supplier": (("proveedor",), ("contratista",), ("adjudicatario",)),
    "buyer": (("comprador",), ("entidad", "contratante")),
}
MAX_ROLE_GAP_TOKENS = 3

POLICY = {
    "coordination_id": COORDINATION_ID,
    "resolver_id": RESOLVER_ID,
    "resolver_version": RESOLVER_VERSION,
    "match_mode": "EXACT_CONTIGUOUS_NORMALIZED_TOKENS_ONLY",
    "fuzzy_similarity": False,
    "substring_matching": False,
    "phonetic_matching": False,
    "automatic_canonical_promotion": False,
    "role_cue_must_be_outside_entity_span": True,
    "max_role_gap_tokens": MAX_ROLE_GAP_TOKENS,
    "registry_aliases_are_pre_normalized": True,
    "evaluation_labels_as_features": False,
    "ground_truth_rtn_as_feature": False,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_value(value: Any) -> str:
    raw = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


POLICY_SHA256 = sha256_value(POLICY)


def require_sha256(value: str, label: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


def _validate_tokens(tokens: Sequence[str], label: str) -> tuple[str, ...]:
    result = tuple(str(token) for token in tokens)
    if not result or any(not _TOKEN_RE.fullmatch(token) for token in result):
        raise ValueError(f"{label} must contain one or more pre-normalized [a-z0-9]+ tokens")
    return result


def validate_registry(registry: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Validate governed pre-normalized rows and fail closed on exact collisions."""
    if not registry:
        raise ValueError("registry must not be empty")
    entities: list[dict[str, Any]] = []
    sequence_owner: dict[tuple[str, ...], str] = {}
    ids_seen: set[str] = set()
    for raw in registry:
        entity_id = str(raw.get("entity_id", "")).strip()
        canonical_name = str(raw.get("canonical_name", "")).strip()
        entity_type = str(raw.get("entity_type", "")).strip()
        record_sha = str(raw.get("registry_record_sha256", ""))
        if not entity_id or not canonical_name or not entity_type:
            raise ValueError("entity_id, canonical_name and entity_type are required")
        require_sha256(record_sha, "registry_record_sha256")
        if entity_id in ids_seen:
            raise ValueError(f"duplicate entity_id: {entity_id}")
        ids_seen.add(entity_id)
        aliases = tuple(
            _validate_tokens(tokens, f"alias_tokens_normalized[{entity_id}]")
            for tokens in raw.get("alias_tokens_normalized", ())
        )
        identifiers = tuple(
            _validate_tokens(tokens, f"identifier_tokens_normalized[{entity_id}]")
            for tokens in raw.get("identifier_tokens_normalized", ())
        )
        if not aliases and not identifiers:
            raise ValueError(f"entity {entity_id} has no exact match sequence")
        for sequence in aliases + identifiers:
            previous = sequence_owner.get(sequence)
            if previous is not None and previous != entity_id:
                raise ValueError(f"registry exact-sequence collision {sequence!r}: {previous} vs {entity_id}")
            sequence_owner[sequence] = entity_id
        entities.append({
            "entity_id": entity_id,
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "registry_record_sha256": record_sha,
            "alias_tokens_normalized": aliases,
            "identifier_tokens_normalized": identifiers,
            "generic_jurisdiction": bool(raw.get("generic_jurisdiction", False)),
        })
    return tuple(sorted(entities, key=lambda row: row["entity_id"]))


def _find_sequence(tokens: Sequence[str], sequence: Sequence[str]) -> list[int]:
    size = len(sequence)
    if size == 0 or size > len(tokens):
        return []
    target = tuple(sequence)
    return [i for i in range(len(tokens) - size + 1) if tuple(tokens[i : i + size]) == target]


def _reconstruct_line(words: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], str, list[tuple[int, int]]]:
    ordered = sorted(words, key=lambda row: (int(row.get("word_num", 0)), int(row.get("left_px", 0)), str(row.get("word_id", ""))))
    text = ""
    spans: list[tuple[int, int]] = []
    for index, word in enumerate(ordered):
        if index:
            text += " "
        start = len(text)
        text += str(word["text_raw"])
        spans.append((start, len(text)))
    return ordered, text, spans


def _bbox_union(words: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    left = min(int(row["left_px"]) for row in words)
    top = min(int(row["top_px"]) for row in words)
    right = max(int(row["left_px"]) + int(row["width_px"]) for row in words)
    bottom = max(int(row["top_px"]) + int(row["height_px"]) for row in words)
    return {"left_px": left, "top_px": top, "width_px": right - left, "height_px": bottom - top}


def _role_support_for_match(tokens: Sequence[str], match_start: int, match_end: int) -> tuple[str | None, bool]:
    """Find one nearby role cue that does not overlap the entity/identifier span."""
    roles: set[str] = set()
    for role, sequences in ROLE_SEQUENCES.items():
        for sequence in sequences:
            for cue_start in _find_sequence(tokens, sequence):
                cue_end = cue_start + len(sequence)
                if cue_end <= match_start:
                    gap = match_start - cue_end
                elif cue_start >= match_end:
                    gap = cue_start - match_end
                else:
                    continue  # cue is inside/overlaps the matched entity sequence
                if gap <= MAX_ROLE_GAP_TOKENS:
                    roles.add(role)
    if len(roles) == 1:
        role = next(iter(roles))
        return role, True
    return None, False


def _group_words_by_line(words: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in words:
        for field in (
            "document_id", "page_id", "word_id", "line_num", "word_num",
            "text_raw", "token_normalized", "left_px", "top_px", "width_px",
            "height_px", "lineage_parent_sha256",
        ):
            if field not in row:
                raise ValueError(f"normalized word missing {field}")
        token = str(row["token_normalized"])
        if token and not _TOKEN_RE.fullmatch(token):
            raise ValueError(f"token_normalized is not canonical: {token!r}")
        line_id = str(row.get("line_id") or "")
        if not line_id:
            word_id = str(row["word_id"])
            if ":w" not in word_id:
                raise ValueError("word has neither line_id nor recoverable v4 word_id")
            line_id = word_id.rsplit(":w", 1)[0]
        grouped[line_id].append(row)
    return grouped


def extract_candidates(
    *,
    words: Sequence[Mapping[str, Any]],
    registry: Sequence[Mapping[str, Any]],
    source_sha256: str,
    normalization_manifest_sha256: str,
) -> list[dict[str, Any]]:
    """Extract deterministic candidates only; no resolution decision is emitted."""
    require_sha256(source_sha256, "source_sha256")
    require_sha256(normalization_manifest_sha256, "normalization_manifest_sha256")
    governed = validate_registry(registry)
    lines = _group_words_by_line(words)
    candidates: dict[str, dict[str, Any]] = {}

    for line_id in sorted(lines):
        ordered, reconstructed, char_spans = _reconstruct_line(lines[line_id])
        tokens = [str(row["token_normalized"]) for row in ordered]
        for entity in governed:
            # One exact sequence can appear in both alias and identifier lists for the
            # same entity. Identifier evidence wins so the span is emitted once.
            match_specs: dict[tuple[str, ...], str] = {
                sequence: "EXACT_ALIAS" for sequence in entity["alias_tokens_normalized"]
            }
            for sequence in entity["identifier_tokens_normalized"]:
                match_specs[sequence] = "EXACT_IDENTIFIER"
            for sequence, match_kind in sorted(match_specs.items()):
                for start in _find_sequence(tokens, sequence):
                    end = start + len(sequence)
                    matched_words = ordered[start:end]
                    span_start, span_end = char_spans[start][0], char_spans[end - 1][1]
                    role, role_supported = _role_support_for_match(tokens, start, end)
                    exact_identifier = match_kind == "EXACT_IDENTIFIER"
                    generic = bool(entity["generic_jurisdiction"])
                    body_support = bool(role_supported and not generic)
                    contextual_only = generic or not body_support
                    registry_support = bool(exact_identifier and body_support and not generic)
                    if generic:
                        hint, rank = "GENERIC_JURISDICTION_ABSTAIN", 0
                    elif body_support and exact_identifier:
                        hint, rank = "EXACT_SOURCE_BOUND_ENTITY", 100
                    elif body_support:
                        hint, rank = "DOCUMENT_LOCAL_ENTITY_MENTION", 90
                    else:
                        hint, rank = "CONTEXTUAL_ORGANIZATION_ONLY", 40
                    basis = {
                        "document_id": str(matched_words[0]["document_id"]),
                        "page_id": str(matched_words[0]["page_id"]),
                        "line_id": line_id,
                        "word_ids": [str(row["word_id"]) for row in matched_words],
                        "source_sha256": source_sha256,
                        "normalization_manifest_sha256": normalization_manifest_sha256,
                        "candidate_type": "ENTITY",
                        "candidate_value_normalized": entity["entity_id"],
                        "span_start": span_start,
                        "span_end": span_end,
                        "resolver_id": RESOLVER_ID,
                        "resolver_version": RESOLVER_VERSION,
                        "policy_sha256": POLICY_SHA256,
                        "match_kind": match_kind,
                        "registry_record_sha256": entity["registry_record_sha256"],
                    }
                    candidate_id = "lane-e:" + sha256_value(basis)
                    row = {
                        **basis,
                        "candidate_id": candidate_id,
                        "candidate_value_display": entity["canonical_name"],
                        "entity_type": entity["entity_type"],
                        "surface_text": reconstructed[span_start:span_end],
                        "bbox": _bbox_union(matched_words),
                        "evidence_channel": "OCR_CONTENT",
                        "role": role,
                        "exclusive_role": role in {"supplier", "buyer"},
                        "body_support": body_support,
                        "registry_support": registry_support,
                        "exact_match": True,
                        "contextual_only": contextual_only,
                        "generic_jurisdiction": generic,
                        "confidence_rank": rank,
                        "resolution_hint": hint,
                        "canonical_promotion": False,
                        "validation_required_downstream": True,
                    }
                    previous = candidates.get(candidate_id)
                    if previous is not None and previous != row:
                        raise RuntimeError("candidate_id collision")
                    candidates[candidate_id] = row
    return [candidates[key] for key in sorted(candidates)]


def build_manifest(
    *, candidates: Sequence[Mapping[str, Any]], source_sha256: str,
    normalization_manifest_sha256: str, registry_manifest_sha256: str,
) -> dict[str, Any]:
    require_sha256(source_sha256, "source_sha256")
    require_sha256(normalization_manifest_sha256, "normalization_manifest_sha256")
    require_sha256(registry_manifest_sha256, "registry_manifest_sha256")
    ordered = sorted((dict(row) for row in candidates), key=lambda row: str(row["candidate_id"]))
    counts: dict[str, int] = defaultdict(int)
    for row in ordered:
        counts[str(row["resolution_hint"])] += 1
    manifest = {
        "schema": SCHEMA,
        "coordination_id": COORDINATION_ID,
        "resolver_id": RESOLVER_ID,
        "resolver_version": RESOLVER_VERSION,
        "policy_sha256": POLICY_SHA256,
        "source_sha256": source_sha256,
        "normalization_manifest_sha256": normalization_manifest_sha256,
        "registry_manifest_sha256": registry_manifest_sha256,
        "candidate_count": len(ordered),
        "candidate_counts_by_hint": dict(sorted(counts.items())),
        "candidate_manifest_sha256": sha256_value(ordered),
        "fuzzy_similarity_used": False,
        "substring_matching_used": False,
        "ground_truth_labels_used_as_features": False,
        "ground_truth_rtn_used_as_feature": False,
        "canonical_promotions": 0,
        "production_writes": 0,
        "external_document_access": 0,
        "external_cost_usd": "0.00",
        "claim_limit": "Software-only exact-match candidates; no external accuracy or production claim.",
        "next_gate": "Downstream validator/arbiter binding, then fresh preregistered document evaluation.",
    }
    manifest["receipt_sha256"] = sha256_value(manifest)
    return manifest


def candidate_public_commitment(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Commitment-only projection; no entity names or OCR text are exported."""
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_type": candidate["candidate_type"],
        "document_id_sha256": sha256_value(str(candidate["document_id"])),
        "page_id_sha256": sha256_value(str(candidate["page_id"])),
        "line_id_sha256": sha256_value(str(candidate["line_id"])),
        "source_sha256": candidate["source_sha256"],
        "normalization_manifest_sha256": candidate["normalization_manifest_sha256"],
        "candidate_value_commitment_sha256": sha256_value(str(candidate["candidate_value_normalized"])),
        "registry_record_sha256": candidate["registry_record_sha256"],
        "policy_sha256": candidate["policy_sha256"],
        "match_kind": candidate["match_kind"],
        "resolution_hint": candidate["resolution_hint"],
        "body_support": candidate["body_support"],
        "registry_support": candidate["registry_support"],
        "generic_jurisdiction": candidate["generic_jurisdiction"],
        "canonical_promotion": False,
    }
