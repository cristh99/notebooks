from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Sequence

SCHEMA = "data-science-pipeline/evidence-scope-receipt/2"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class EvidenceChannel(str, Enum):
    SOURCE_PROVENANCE = "source_provenance"
    DOCUMENT_METADATA = "document_metadata"
    OCR_CONTENT = "ocr_content"
    NATIVE_CONTROL = "native_control"


class ClaimScope(str, Enum):
    SOURCE_IDENTITY = "source_identity"
    DOCUMENT_CONTENT = "document_content"


class ResolutionState(str, Enum):
    MATCH_OFFICIAL = "MATCH_OFFICIAL"
    MATCH_VALIDATED = "MATCH_VALIDATED"
    CANDIDATE_REVIEW = "CANDIDATE_REVIEW"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    NO_MATCH_OBSERVED = "NO_MATCH_OBSERVED"
    QUARANTINED = "QUARANTINED"


_ALLOWED_CHANNELS: Mapping[
    ClaimScope,
    Mapping[str, frozenset[EvidenceChannel]],
] = MappingProxyType(
    {
        ClaimScope.SOURCE_IDENTITY: MappingProxyType(
            {
                "confirmation": frozenset(
                    {
                        EvidenceChannel.SOURCE_PROVENANCE,
                        EvidenceChannel.OCR_CONTENT,
                    }
                ),
                "diagnostic": frozenset({EvidenceChannel.NATIVE_CONTROL}),
                "metadata": frozenset({EvidenceChannel.DOCUMENT_METADATA}),
            }
        ),
        ClaimScope.DOCUMENT_CONTENT: MappingProxyType(
            {
                "confirmation": frozenset({EvidenceChannel.OCR_CONTENT}),
                "diagnostic": frozenset({EvidenceChannel.NATIVE_CONTROL}),
                "metadata": frozenset({EvidenceChannel.DOCUMENT_METADATA}),
            }
        ),
    }
)


@dataclass(frozen=True)
class ClaimRequirement:
    claim_id: str
    scope: ClaimScope
    tokens: tuple[str, ...]
    confirmation_channels: tuple[EvidenceChannel, ...]
    hard: bool
    diagnostic_channels: tuple[EvidenceChannel, ...] = ()
    metadata_channels: tuple[EvidenceChannel, ...] = ()
    match_mode: str = "all"

    def __post_init__(self) -> None:
        if not self.claim_id.strip():
            raise ValueError("claim_id must not be blank")
        if not isinstance(self.scope, ClaimScope):
            raise TypeError("scope must be a ClaimScope")
        if not self.tokens:
            raise ValueError("tokens must not be empty")
        normalized_tokens = tuple(normalize_text(token) for token in self.tokens)
        if any(not token for token in normalized_tokens):
            raise ValueError("tokens must contain alphanumeric content")
        if len(set(normalized_tokens)) != len(normalized_tokens):
            raise ValueError("tokens must be unique after normalization")
        if not self.confirmation_channels:
            raise ValueError("confirmation_channels must not be empty")
        if self.match_mode not in {"all", "any"}:
            raise ValueError("match_mode must be 'all' or 'any'")

        groups = {
            "confirmation": self.confirmation_channels,
            "diagnostic": self.diagnostic_channels,
            "metadata": self.metadata_channels,
        }
        allowed = _ALLOWED_CHANNELS[self.scope]
        for group_name, channels in groups.items():
            if len(set(channels)) != len(channels):
                raise ValueError(f"{group_name}_channels must be unique")
            if any(not isinstance(channel, EvidenceChannel) for channel in channels):
                raise TypeError("all evidence channels must be EvidenceChannel values")
            disallowed = set(channels) - allowed[group_name]
            if disallowed:
                names = sorted(channel.value for channel in disallowed)
                raise ValueError(
                    f"{self.scope.value} cannot use {names} as {group_name} evidence"
                )


@dataclass(frozen=True)
class EvidenceBundle:
    observations: Mapping[EvidenceChannel, str]
    channel_receipts: Mapping[EvidenceChannel, str]
    processed_pages: tuple[int, ...]
    total_pages: int
    partial_document: bool
    integrity_ok: bool = True
    integrity_reason: str = "INTEGRITY_OK"

    def __post_init__(self) -> None:
        observation_snapshot = dict(self.observations)
        receipt_snapshot = dict(self.channel_receipts)
        if any(not isinstance(channel, EvidenceChannel) for channel in observation_snapshot):
            raise TypeError("observation keys must be EvidenceChannel values")
        if any(not isinstance(text, str) for text in observation_snapshot.values()):
            raise TypeError("observation values must be strings")
        if any(not isinstance(channel, EvidenceChannel) for channel in receipt_snapshot):
            raise TypeError("receipt keys must be EvidenceChannel values")
        if not set(receipt_snapshot).issubset(observation_snapshot):
            raise ValueError("validated channel receipt has no observation")
        for digest in receipt_snapshot.values():
            if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
                raise ValueError("channel receipts must be lowercase SHA-256 digests")

        object.__setattr__(
            self,
            "observations",
            MappingProxyType(observation_snapshot),
        )
        object.__setattr__(
            self,
            "channel_receipts",
            MappingProxyType(receipt_snapshot),
        )

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

    @property
    def validated_channels(self) -> frozenset[EvidenceChannel]:
        return frozenset(self.channel_receipts)


@dataclass(frozen=True)
class ClaimDecision:
    claim_id: str
    scope: ClaimScope
    state: ResolutionState
    reason_code: str
    hard: bool
    matched_tokens: tuple[str, ...]
    supporting_channels: tuple[EvidenceChannel, ...]
    metadata_channels: tuple[EvidenceChannel, ...]
    unvalidated_observed_channels: tuple[EvidenceChannel, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "scope": self.scope.value,
            "state": self.state.value,
            "reason_code": self.reason_code,
            "hard": self.hard,
            "matched_tokens": list(self.matched_tokens),
            "supporting_channels": [
                channel.value for channel in self.supporting_channels
            ],
            "metadata_channels": [
                channel.value for channel in self.metadata_channels
            ],
            "unvalidated_observed_channels": [
                channel.value for channel in self.unvalidated_observed_channels
            ],
        }


@dataclass(frozen=True)
class BundleDecision:
    verdict: str
    claims: tuple[ClaimDecision, ...]
    channel_receipts: tuple[tuple[EvidenceChannel, str], ...]
    processed_pages: tuple[int, ...]
    total_pages: int
    partial_document: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "verdict": self.verdict,
            "channel_receipts": {
                channel.value: digest for channel, digest in self.channel_receipts
            },
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
    unaccented = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"[^A-Z0-9]+", " ", unaccented.upper()).strip()


def _channel_tokens(
    bundle: EvidenceBundle,
    channel: EvidenceChannel,
) -> frozenset[str]:
    return frozenset(normalize_text(bundle.observations.get(channel, "")).split())


def _matches(
    requirement: ClaimRequirement,
    token_set: frozenset[str],
) -> tuple[bool, tuple[str, ...]]:
    expected = tuple(normalize_text(token) for token in requirement.tokens)
    hits = tuple(token for token in expected if token in token_set)
    if requirement.match_mode == "all":
        return len(hits) == len(expected), hits
    return bool(hits), hits


def _matching_channels(
    requirement: ClaimRequirement,
    bundle: EvidenceBundle,
    channels: Sequence[EvidenceChannel],
    *,
    require_validated: bool,
) -> tuple[tuple[EvidenceChannel, ...], tuple[str, ...]]:
    matched_channels: list[EvidenceChannel] = []
    matched_tokens: set[str] = set()
    for channel in channels:
        if require_validated and channel not in bundle.channel_receipts:
            continue
        matched, hits = _matches(requirement, _channel_tokens(bundle, channel))
        if matched:
            matched_channels.append(channel)
            matched_tokens.update(hits)
    return tuple(matched_channels), tuple(sorted(matched_tokens))


def _official_confirmation(channels: Sequence[EvidenceChannel]) -> bool:
    return any(
        channel is EvidenceChannel.SOURCE_PROVENANCE for channel in channels
    )


def _decision(
    requirement: ClaimRequirement,
    *,
    state: ResolutionState,
    reason_code: str,
    matched_tokens: tuple[str, ...] = (),
    supporting_channels: tuple[EvidenceChannel, ...] = (),
    metadata_channels: tuple[EvidenceChannel, ...] = (),
    unvalidated_observed_channels: tuple[EvidenceChannel, ...] = (),
) -> ClaimDecision:
    return ClaimDecision(
        claim_id=requirement.claim_id,
        scope=requirement.scope,
        state=state,
        reason_code=reason_code,
        hard=requirement.hard,
        matched_tokens=matched_tokens,
        supporting_channels=supporting_channels,
        metadata_channels=metadata_channels,
        unvalidated_observed_channels=unvalidated_observed_channels,
    )


def evaluate_claim(
    bundle: EvidenceBundle,
    requirement: ClaimRequirement,
) -> ClaimDecision:
    if not bundle.integrity_ok:
        return _decision(
            requirement,
            state=ResolutionState.QUARANTINED,
            reason_code=bundle.integrity_reason,
        )

    confirmation_channels, confirmation_tokens = _matching_channels(
        requirement,
        bundle,
        requirement.confirmation_channels,
        require_validated=True,
    )
    if confirmation_channels:
        state = (
            ResolutionState.MATCH_OFFICIAL
            if _official_confirmation(confirmation_channels)
            else ResolutionState.MATCH_VALIDATED
        )
        return _decision(
            requirement,
            state=state,
            reason_code=(
                "OFFICIAL_ID_EXACT"
                if state is ResolutionState.MATCH_OFFICIAL
                else "EVIDENCE_SCOPED_CONTENT_MATCH"
            ),
            matched_tokens=confirmation_tokens,
            supporting_channels=confirmation_channels,
        )

    raw_confirmation_channels, raw_confirmation_tokens = _matching_channels(
        requirement,
        bundle,
        requirement.confirmation_channels,
        require_validated=False,
    )
    if raw_confirmation_channels:
        return _decision(
            requirement,
            state=ResolutionState.NOT_EVALUABLE,
            reason_code="EVIDENCE_CHANNEL_NOT_VALIDATED",
            matched_tokens=raw_confirmation_tokens,
            unvalidated_observed_channels=raw_confirmation_channels,
        )

    diagnostic_channels, diagnostic_tokens = _matching_channels(
        requirement,
        bundle,
        requirement.diagnostic_channels,
        require_validated=True,
    )
    if diagnostic_channels:
        return _decision(
            requirement,
            state=ResolutionState.QUARANTINED,
            reason_code="OCR_REQUIRED_TOKEN_MISSED",
            matched_tokens=diagnostic_tokens,
            supporting_channels=diagnostic_channels,
        )

    raw_diagnostic_channels, raw_diagnostic_tokens = _matching_channels(
        requirement,
        bundle,
        requirement.diagnostic_channels,
        require_validated=False,
    )
    if raw_diagnostic_channels:
        return _decision(
            requirement,
            state=ResolutionState.NOT_EVALUABLE,
            reason_code="EVIDENCE_CHANNEL_NOT_VALIDATED",
            matched_tokens=raw_diagnostic_tokens,
            unvalidated_observed_channels=raw_diagnostic_channels,
        )

    metadata_channels, metadata_tokens = _matching_channels(
        requirement,
        bundle,
        requirement.metadata_channels,
        require_validated=True,
    )
    if metadata_channels:
        if bundle.partial_document and requirement.hard:
            return _decision(
                requirement,
                state=ResolutionState.NOT_EVALUABLE,
                reason_code="PARTIAL_SCOPE_NOT_COVERED",
                matched_tokens=metadata_tokens,
                metadata_channels=metadata_channels,
            )
        return _decision(
            requirement,
            state=ResolutionState.CANDIDATE_REVIEW,
            reason_code="METADATA_ONLY_NOT_CONTENT_IDENTITY",
            matched_tokens=metadata_tokens,
            metadata_channels=metadata_channels,
        )

    raw_metadata_channels, raw_metadata_tokens = _matching_channels(
        requirement,
        bundle,
        requirement.metadata_channels,
        require_validated=False,
    )
    if raw_metadata_channels:
        return _decision(
            requirement,
            state=ResolutionState.NOT_EVALUABLE,
            reason_code="EVIDENCE_CHANNEL_NOT_VALIDATED",
            matched_tokens=raw_metadata_tokens,
            unvalidated_observed_channels=raw_metadata_channels,
        )

    if bundle.partial_document:
        return _decision(
            requirement,
            state=ResolutionState.NOT_EVALUABLE,
            reason_code="PARTIAL_SCOPE_NOT_COVERED",
        )

    return _decision(
        requirement,
        state=ResolutionState.NO_MATCH_OBSERVED,
        reason_code="NO_MATCH_OBSERVED_IN_FULL_SCOPE",
    )


def evaluate_bundle(
    bundle: EvidenceBundle,
    requirements: Sequence[ClaimRequirement],
) -> BundleDecision:
    if not requirements:
        raise ValueError("requirements must not be empty")
    if len({requirement.claim_id for requirement in requirements}) != len(
        requirements
    ):
        raise ValueError("claim_id values must be unique")

    decisions = tuple(
        evaluate_claim(bundle, requirement) for requirement in requirements
    )
    if any(
        decision.state is ResolutionState.QUARANTINED for decision in decisions
    ):
        verdict = "QUARANTINED"
    elif any(
        decision.hard
        and decision.state
        not in {
            ResolutionState.MATCH_OFFICIAL,
            ResolutionState.MATCH_VALIDATED,
        }
        for decision in decisions
    ):
        verdict = "ABSTAIN"
    else:
        verdict = "PASS_SCOPED"

    return BundleDecision(
        verdict=verdict,
        claims=decisions,
        channel_receipts=tuple(
            sorted(bundle.channel_receipts.items(), key=lambda item: item[0].value)
        ),
        processed_pages=bundle.processed_pages,
        total_pages=bundle.total_pages,
        partial_document=bundle.partial_document,
    )
