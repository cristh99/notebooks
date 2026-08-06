from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

SCHEMA = "data-science-pipeline/evidence-scope-receipt/1"


class EvidenceChannel(str, Enum):
    SOURCE_PROVENANCE = "source_provenance"
    DOCUMENT_METADATA = "document_metadata"
    OCR_CONTENT = "ocr_content"
    NATIVE_CONTROL = "native_control"


class ResolutionState(str, Enum):
    MATCH_OFFICIAL = "MATCH_OFFICIAL"
    MATCH_VALIDATED = "MATCH_VALIDATED"
    CANDIDATE_REVIEW = "CANDIDATE_REVIEW"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    NO_MATCH_OBSERVED = "NO_MATCH_OBSERVED"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class ClaimRequirement:
    claim_id: str
    tokens: tuple[str, ...]
    confirmation_channels: tuple[EvidenceChannel, ...]
    hard: bool
    diagnostic_channels: tuple[EvidenceChannel, ...] = ()
    metadata_channels: tuple[EvidenceChannel, ...] = ()
    match_mode: str = "all"

    def __post_init__(self) -> None:
        if not self.claim_id.strip():
            raise ValueError("claim_id must not be blank")
        if not self.tokens:
            raise ValueError("tokens must not be empty")
        if not self.confirmation_channels:
            raise ValueError("confirmation_channels must not be empty")
        if self.match_mode not in {"all", "any"}:
            raise ValueError("match_mode must be 'all' or 'any'")
        if len(set(self.tokens)) != len(self.tokens):
            raise ValueError("tokens must be unique")


@dataclass(frozen=True)
class EvidenceBundle:
    observations: Mapping[EvidenceChannel, str]
    processed_pages: tuple[int, ...]
    total_pages: int
    partial_document: bool
    integrity_ok: bool = True
    integrity_reason: str = "INTEGRITY_OK"

    def __post_init__(self) -> None:
        if self.total_pages <= 0:
            raise ValueError("total_pages must be positive")
        if not self.processed_pages:
            raise ValueError("processed_pages must not be empty")
        if tuple(sorted(set(self.processed_pages))) != self.processed_pages:
            raise ValueError("processed_pages must be unique and sorted")
        if min(self.processed_pages) < 1 or max(self.processed_pages) > self.total_pages:
            raise ValueError("processed_pages outside document bounds")
        if not self.partial_document and len(self.processed_pages) != self.total_pages:
            raise ValueError("full document must include every page")
        if self.partial_document and len(self.processed_pages) >= self.total_pages:
            raise ValueError("partial_document requires incomplete page coverage")
        if not self.integrity_ok and self.integrity_reason == "INTEGRITY_OK":
            raise ValueError("integrity failure requires a reason code")


@dataclass(frozen=True)
class ClaimDecision:
    claim_id: str
    state: ResolutionState
    reason_code: str
    hard: bool
    matched_tokens: tuple[str, ...]
    supporting_channels: tuple[EvidenceChannel, ...]
    metadata_channels: tuple[EvidenceChannel, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "state": self.state.value,
            "reason_code": self.reason_code,
            "hard": self.hard,
            "matched_tokens": list(self.matched_tokens),
            "supporting_channels": [channel.value for channel in self.supporting_channels],
            "metadata_channels": [channel.value for channel in self.metadata_channels],
        }


@dataclass(frozen=True)
class BundleDecision:
    verdict: str
    claims: tuple[ClaimDecision, ...]
    processed_pages: tuple[int, ...]
    total_pages: int
    partial_document: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "verdict": self.verdict,
            "processed_pages": list(self.processed_pages),
            "total_pages": self.total_pages,
            "partial_document": self.partial_document,
            "claims": [claim.to_dict() for claim in self.claims],
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", unaccented.upper()).strip()


def _channel_tokens(bundle: EvidenceBundle, channel: EvidenceChannel) -> frozenset[str]:
    return frozenset(normalize_text(bundle.observations.get(channel, "")).split())


def _matches(requirement: ClaimRequirement, token_set: frozenset[str]) -> tuple[bool, tuple[str, ...]]:
    expected = tuple(normalize_text(token) for token in requirement.tokens)
    hits = tuple(token for token in expected if token in token_set)
    if requirement.match_mode == "all":
        return len(hits) == len(expected), hits
    return bool(hits), hits


def _matching_channels(
    requirement: ClaimRequirement,
    bundle: EvidenceBundle,
    channels: Sequence[EvidenceChannel],
) -> tuple[tuple[EvidenceChannel, ...], tuple[str, ...]]:
    matched_channels: list[EvidenceChannel] = []
    matched_tokens: set[str] = set()
    for channel in channels:
        matched, hits = _matches(requirement, _channel_tokens(bundle, channel))
        if matched:
            matched_channels.append(channel)
            matched_tokens.update(hits)
    return tuple(matched_channels), tuple(sorted(matched_tokens))


def _official_confirmation(channels: Sequence[EvidenceChannel]) -> bool:
    return any(channel is EvidenceChannel.SOURCE_PROVENANCE for channel in channels)


def evaluate_claim(bundle: EvidenceBundle, requirement: ClaimRequirement) -> ClaimDecision:
    if not bundle.integrity_ok:
        return ClaimDecision(
            claim_id=requirement.claim_id,
            state=ResolutionState.QUARANTINED,
            reason_code=bundle.integrity_reason,
            hard=requirement.hard,
            matched_tokens=(),
            supporting_channels=(),
            metadata_channels=(),
        )

    confirmation_channels, confirmation_tokens = _matching_channels(
        requirement, bundle, requirement.confirmation_channels
    )
    if confirmation_channels:
        state = (
            ResolutionState.MATCH_OFFICIAL
            if _official_confirmation(confirmation_channels)
            else ResolutionState.MATCH_VALIDATED
        )
        reason = "OFFICIAL_ID_EXACT" if state is ResolutionState.MATCH_OFFICIAL else "EVIDENCE_SCOPED_CONTENT_MATCH"
        return ClaimDecision(
            claim_id=requirement.claim_id,
            state=state,
            reason_code=reason,
            hard=requirement.hard,
            matched_tokens=confirmation_tokens,
            supporting_channels=confirmation_channels,
            metadata_channels=(),
        )

    diagnostic_channels, diagnostic_tokens = _matching_channels(
        requirement, bundle, requirement.diagnostic_channels
    )
    if diagnostic_channels:
        return ClaimDecision(
            claim_id=requirement.claim_id,
            state=ResolutionState.QUARANTINED,
            reason_code="OCR_REQUIRED_TOKEN_MISSED",
            hard=requirement.hard,
            matched_tokens=diagnostic_tokens,
            supporting_channels=diagnostic_channels,
            metadata_channels=(),
        )

    metadata_channels, metadata_tokens = _matching_channels(
        requirement, bundle, requirement.metadata_channels
    )
    if metadata_channels:
        if bundle.partial_document and requirement.hard:
            return ClaimDecision(
                claim_id=requirement.claim_id,
                state=ResolutionState.NOT_EVALUABLE,
                reason_code="PARTIAL_SCOPE_NOT_COVERED",
                hard=requirement.hard,
                matched_tokens=metadata_tokens,
                supporting_channels=(),
                metadata_channels=metadata_channels,
            )
        return ClaimDecision(
            claim_id=requirement.claim_id,
            state=ResolutionState.CANDIDATE_REVIEW,
            reason_code="METADATA_ONLY_NOT_CONTENT_IDENTITY",
            hard=requirement.hard,
            matched_tokens=metadata_tokens,
            supporting_channels=(),
            metadata_channels=metadata_channels,
        )

    if bundle.partial_document:
        return ClaimDecision(
            claim_id=requirement.claim_id,
            state=ResolutionState.NOT_EVALUABLE,
            reason_code="PARTIAL_SCOPE_NOT_COVERED",
            hard=requirement.hard,
            matched_tokens=(),
            supporting_channels=(),
            metadata_channels=(),
        )

    return ClaimDecision(
        claim_id=requirement.claim_id,
        state=ResolutionState.NO_MATCH_OBSERVED,
        reason_code="NO_MATCH_OBSERVED_IN_FULL_SCOPE",
        hard=requirement.hard,
        matched_tokens=(),
        supporting_channels=(),
        metadata_channels=(),
    )


def evaluate_bundle(
    bundle: EvidenceBundle,
    requirements: Sequence[ClaimRequirement],
) -> BundleDecision:
    if not requirements:
        raise ValueError("requirements must not be empty")
    if len({requirement.claim_id for requirement in requirements}) != len(requirements):
        raise ValueError("claim_id values must be unique")

    decisions = tuple(evaluate_claim(bundle, requirement) for requirement in requirements)
    if any(decision.state is ResolutionState.QUARANTINED for decision in decisions):
        verdict = "QUARANTINED"
    elif any(
        decision.hard
        and decision.state not in {ResolutionState.MATCH_OFFICIAL, ResolutionState.MATCH_VALIDATED}
        for decision in decisions
    ):
        verdict = "ABSTAIN"
    else:
        verdict = "PASS_SCOPED"

    return BundleDecision(
        verdict=verdict,
        claims=decisions,
        processed_pages=bundle.processed_pages,
        total_pages=bundle.total_pages,
        partial_document=bundle.partial_document,
    )
