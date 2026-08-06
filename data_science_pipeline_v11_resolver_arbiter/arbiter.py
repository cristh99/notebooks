from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Sequence


class CandidateKind(str, Enum):
    ENTITY = "ENTITY"
    NUMERIC = "NUMERIC"


class EvidenceChannel(str, Enum):
    SOURCE_PROVENANCE = "SOURCE_PROVENANCE"
    DOCUMENT_METADATA = "DOCUMENT_METADATA"
    OCR_CONTENT = "OCR_CONTENT"
    NATIVE_CONTROL = "NATIVE_CONTROL"
    GOVERNED_REGISTRY = "GOVERNED_REGISTRY"


class SemanticClass(str, Enum):
    MONETARY_AMOUNT = "MONETARY_AMOUNT"
    CALENDAR_DATE = "CALENDAR_DATE"
    FISCAL_PERIOD = "FISCAL_PERIOD"
    LEGAL_INSTRUMENT_ID = "LEGAL_INSTRUMENT_ID"
    TELEPHONE = "TELEPHONE"
    PAGE_OR_LIST_NUMBER = "PAGE_OR_LIST_NUMBER"
    UNRESOLVED_NUMERIC = "UNRESOLVED_NUMERIC"


class DecisionStatus(str, Enum):
    ACCEPT = "ACCEPT"
    ABSTAIN = "ABSTAIN"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class TrustEvidence:
    validator_id: str
    validation_receipt_sha256: str
    policy_sha256: str
    validator_registry_sha256: str
    signature_valid: bool
    registry_hash_matches: bool
    policy_authorized: bool
    channel_authorized: bool
    native_control_contradicts: bool = False


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    kind: CandidateKind
    document_id: str
    page_id: str
    source_sha256: str
    normalization_manifest_sha256: str
    candidate_value_normalized: str
    candidate_value_display: str
    evidence_channel: EvidenceChannel
    trust: TrustEvidence
    line_id: str | None = None
    word_ids: tuple[str, ...] = ()
    resolver_id: str = ""
    resolver_version: str = ""
    role: str | None = None
    semantic_class: SemanticClass | None = None
    context: str = ""
    exclusive_role: bool = False
    source_hash_verified: bool = True
    normalization_hash_verified: bool = True
    body_support: bool = False
    registry_support: bool = False
    exact_match: bool = False
    contextual_only: bool = False
    generic_jurisdiction: bool = False
    confidence_rank: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "document_id",
            "page_id",
            "source_sha256",
            "normalization_manifest_sha256",
            "candidate_value_normalized",
            "candidate_value_display",
            "resolver_id",
            "resolver_version",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        for digest_name in (
            "source_sha256",
            "normalization_manifest_sha256",
            "trust.validation_receipt_sha256",
            "trust.policy_sha256",
            "trust.validator_registry_sha256",
        ):
            value = _nested_get(self, digest_name)
            if not _is_sha256(value):
                raise ValueError(f"{digest_name} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True)
class Decision:
    candidate_ids: tuple[str, ...]
    status: DecisionStatus
    code: str
    resolved_value: str | None
    semantic_class: SemanticClass | None
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_ids": list(self.candidate_ids),
            "status": self.status.value,
            "code": self.code,
            "resolved_value": self.resolved_value,
            "semantic_class": self.semantic_class.value if self.semantic_class else None,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class Receipt:
    coordination_id: str
    arbiter_version: str
    input_manifest_sha256: str
    policy_sha256: str
    validator_registry_sha256: str
    candidate_count_by_lane: Mapping[str, int]
    accepted_count: int
    abstained_count: int
    quarantined_count: int
    rejected_count: int
    decisions: tuple[Decision, ...]
    external_cost_usd: Decimal
    production_writes: int
    claim_limit: str
    next_gate: str
    replay_digest: str

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "coordination_id": self.coordination_id,
            "arbiter_version": self.arbiter_version,
            "input_manifest_sha256": self.input_manifest_sha256,
            "policy_sha256": self.policy_sha256,
            "validator_registry_sha256": self.validator_registry_sha256,
            "candidate_count_by_lane": dict(sorted(self.candidate_count_by_lane.items())),
            "accepted_count": self.accepted_count,
            "abstained_count": self.abstained_count,
            "quarantined_count": self.quarantined_count,
            "rejected_count": self.rejected_count,
            "decisions": [d.to_dict() for d in self.decisions],
            "external_cost_usd": format(self.external_cost_usd, "f"),
            "production_writes": self.production_writes,
            "claim_limit": self.claim_limit,
            "next_gate": self.next_gate,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.unsigned_dict()
        payload["replay_digest"] = self.replay_digest
        return payload


_PHONE_RE = re.compile(r"^\+?\d[\d\s().-]{6,}\d$")
_LEGAL_ID_RE = re.compile(
    r"(?i)\b(?:decreto(?:\s+legislativo)?|acuerdo|resoluci[oó]n|ley)\s*(?:no\.?\s*)?(\d{1,4}-\d{2,4})\b"
)
_DATE_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})$")
_CURRENCY_PREFIX_RE = re.compile(
    r"(?i)^(?:L(?:\.\s*|\s+)|HNL\s+|\$\s*|USD\s+)([0-9][0-9.,]*)$"
)
_CURRENCY_SUFFIX_RE = re.compile(r"(?i)^([0-9][0-9.,]*)\s+(?:lempiras?|d[oó]lares?|usd)$")
_FISCAL_RE = re.compile(r"(?i)\b(?:ejercicio|año|periodo)\s+fiscal\s+(\d{4})\b")


def _nested_get(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        current = getattr(current, part)
    return current


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def canonical_json(value: Any) -> str:
    """Serialize strict, finite, deterministic JSON."""
    _assert_finite(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def strict_json_loads(text: str) -> Any:
    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite JSON constant: {token}")

    value = json.loads(text, parse_constant=reject_constant, parse_float=Decimal)
    _assert_finite(value)
    return value


def _assert_finite(value: Any) -> None:
    if dataclasses.is_dataclass(value):
        _assert_finite(dataclasses.asdict(value))
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float")
        return
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal")
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _assert_finite(key)
            _assert_finite(nested)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            _assert_finite(nested)


def classify_numeric(text: str, context: str = "") -> SemanticClass:
    stripped = " ".join(text.strip().split())
    combined = f"{context} {stripped}".strip()

    if _LEGAL_ID_RE.search(combined):
        return SemanticClass.LEGAL_INSTRUMENT_ID
    if _FISCAL_RE.search(combined):
        return SemanticClass.FISCAL_PERIOD
    if _PHONE_RE.fullmatch(stripped) and (
        stripped.startswith("+") or len(re.sub(r"\D", "", stripped)) >= 8
    ):
        return SemanticClass.TELEPHONE
    if _DATE_RE.fullmatch(stripped):
        return SemanticClass.CALENDAR_DATE
    if _CURRENCY_PREFIX_RE.fullmatch(stripped) or _CURRENCY_SUFFIX_RE.fullmatch(stripped):
        return SemanticClass.MONETARY_AMOUNT
    if re.fullmatch(r"\d{1,3}", stripped) and re.search(
        r"(?i)\b(?:p[aá]gina|p[aá]g\.?|item|numeral|cap[ií]tulo|secci[oó]n)\b",
        context,
    ):
        return SemanticClass.PAGE_OR_LIST_NUMBER
    return SemanticClass.UNRESOLVED_NUMERIC


def _trust_failure(candidate: Candidate) -> Decision | None:
    ids = (candidate.candidate_id,)
    if not candidate.source_hash_verified or not candidate.normalization_hash_verified:
        return Decision(
            ids,
            DecisionStatus.QUARANTINE,
            "QUARANTINE_MISSING_OR_ALTERED_LINEAGE",
            None,
            candidate.semantic_class,
            "Source or normalization hash did not verify.",
        )
    trust = candidate.trust
    if not trust.signature_valid or not trust.registry_hash_matches:
        return Decision(
            ids,
            DecisionStatus.QUARANTINE,
            "VALIDATOR_TRUST_QUARANTINE",
            None,
            candidate.semantic_class,
            "Validator signature or registry binding failed.",
        )
    if not trust.policy_authorized or not trust.channel_authorized:
        return Decision(
            ids,
            DecisionStatus.REJECT,
            "CHANNEL_SCOPE_REJECT",
            None,
            candidate.semantic_class,
            "Validator was not authorized for the policy/channel.",
        )
    if trust.native_control_contradicts:
        return Decision(
            ids,
            DecisionStatus.QUARANTINE,
            "OCR_CANDIDATE_QUARANTINE",
            None,
            candidate.semantic_class,
            "Independent native-control evidence contradicted the OCR candidate.",
        )
    return None


def arbitrate_entities(candidates: Sequence[Candidate]) -> Decision:
    if not candidates:
        return Decision(
            (),
            DecisionStatus.ABSTAIN,
            "INSUFFICIENT_EVIDENCE",
            None,
            None,
            "No entity candidate was supplied.",
        )
    for candidate in candidates:
        if candidate.kind is not CandidateKind.ENTITY:
            raise ValueError("entity arbitration received a non-entity candidate")
        trust_failure = _trust_failure(candidate)
        if trust_failure:
            return trust_failure

    candidate_ids = tuple(sorted(c.candidate_id for c in candidates))
    if any(c.generic_jurisdiction for c in candidates):
        return Decision(
            candidate_ids,
            DecisionStatus.ABSTAIN,
            "GENERIC_JURISDICTION_ABSTAIN",
            None,
            None,
            "Generic jurisdiction text is not a complete legal entity identity.",
        )

    promotable = [c for c in candidates if (c.exact_match and c.body_support) or c.registry_support]
    if not promotable:
        if any(c.contextual_only for c in candidates):
            contextual = sorted(
                (c for c in candidates if c.contextual_only),
                key=lambda c: (-c.confidence_rank, c.candidate_id),
            )[0]
            return Decision(
                candidate_ids,
                DecisionStatus.ABSTAIN,
                "CONTEXTUAL_ORGANIZATION_ONLY",
                contextual.candidate_value_normalized,
                None,
                "The organization is mentioned only as context, not as the claimed role.",
            )
        return Decision(
            candidate_ids,
            DecisionStatus.ABSTAIN,
            "INSUFFICIENT_EVIDENCE",
            None,
            None,
            "No candidate had body-role support or governed registry support.",
        )

    best_rank = max(c.confidence_rank for c in promotable)
    best = [c for c in promotable if c.confidence_rank == best_rank]
    distinct_values = sorted({c.candidate_value_normalized for c in best})
    if len(distinct_values) > 1 and any(c.exclusive_role for c in best):
        return Decision(
            candidate_ids,
            DecisionStatus.ABSTAIN,
            "COLLISION_ABSTAIN",
            None,
            None,
            "Equal-strength candidates conflict for an exclusive role.",
        )
    selected = sorted(best, key=lambda c: (c.candidate_value_normalized, c.candidate_id))[0]
    if selected.evidence_channel is EvidenceChannel.DOCUMENT_METADATA and not selected.body_support:
        return Decision(
            candidate_ids,
            DecisionStatus.REJECT,
            "CHANNEL_SCOPE_REJECT",
            None,
            None,
            "Document metadata cannot substitute for document-body role support.",
        )
    return Decision(
        candidate_ids,
        DecisionStatus.ACCEPT,
        "EXACT_SOURCE_BOUND_ENTITY",
        selected.candidate_value_normalized,
        None,
        "Exact source-bound entity with role support passed all trust and collision gates.",
    )


def arbitrate_numeric(candidate: Candidate) -> Decision:
    if candidate.kind is not CandidateKind.NUMERIC:
        raise ValueError("numeric arbitration received a non-numeric candidate")
    trust_failure = _trust_failure(candidate)
    if trust_failure:
        return trust_failure

    inferred = classify_numeric(candidate.candidate_value_display, candidate.context)
    supplied = candidate.semantic_class or inferred
    if candidate.semantic_class is not None and candidate.semantic_class != inferred:
        return Decision(
            (candidate.candidate_id,),
            DecisionStatus.ABSTAIN,
            "CLASS_CONFLICT_ABSTAIN",
            None,
            inferred,
            "Declared and independently inferred numeric classes conflict.",
        )
    if inferred is SemanticClass.UNRESOLVED_NUMERIC:
        return Decision(
            (candidate.candidate_id,),
            DecisionStatus.ABSTAIN,
            "UNRESOLVED_NUMERIC_ABSTAIN",
            None,
            inferred,
            "Numeric token lacks sufficient class and role evidence.",
        )
    if inferred in {
        SemanticClass.TELEPHONE,
        SemanticClass.PAGE_OR_LIST_NUMBER,
        SemanticClass.LEGAL_INSTRUMENT_ID,
        SemanticClass.FISCAL_PERIOD,
    }:
        return Decision(
            (candidate.candidate_id,),
            DecisionStatus.ACCEPT,
            f"CLASSIFIED_{inferred.value}",
            candidate.candidate_value_normalized,
            inferred,
            "The token was accepted only in its non-monetary semantic class.",
        )
    if inferred in {SemanticClass.MONETARY_AMOUNT, SemanticClass.CALENDAR_DATE}:
        if not candidate.body_support:
            return Decision(
                (candidate.candidate_id,),
                DecisionStatus.ABSTAIN,
                "INSUFFICIENT_ROLE_CONTEXT",
                None,
                inferred,
                "Amount/date candidate lacks document-body role support.",
            )
        return Decision(
            (candidate.candidate_id,),
            DecisionStatus.ACCEPT,
            f"EXACT_SOURCE_BOUND_{inferred.value}",
            candidate.candidate_value_normalized,
            inferred,
            "Class-specific syntax, body context and trust gates passed.",
        )
    return Decision(
        (candidate.candidate_id,),
        DecisionStatus.ABSTAIN,
        "INSUFFICIENT_EVIDENCE",
        None,
        supplied,
        "No promotion rule matched.",
    )


def build_receipt(
    *,
    candidates: Sequence[Candidate],
    decisions: Sequence[Decision],
    coordination_id: str = "COORD-2026-08-06-PARALLEL-V2",
    arbiter_version: str = "DATA-SCIENCE-RESOLVER-ARBITER-V1-20260806",
    external_cost_usd: Decimal = Decimal("0"),
    production_writes: int = 0,
    claim_limit: str = (
        "Software arbitration only; no external accuracy, payment, legality, "
        "intent, corruption or production claim."
    ),
    next_gate: str = "Fresh preregistered external document evaluation.",
) -> Receipt:
    if not candidates:
        raise ValueError("at least one candidate is required")
    ordered_candidates = sorted(candidates, key=lambda c: c.candidate_id)
    candidate_payload = [_candidate_to_dict(c) for c in ordered_candidates]
    input_manifest_sha256 = hashlib.sha256(
        canonical_json(candidate_payload).encode("utf-8")
    ).hexdigest()
    policy_hashes = {c.trust.policy_sha256 for c in ordered_candidates}
    registry_hashes = {c.trust.validator_registry_sha256 for c in ordered_candidates}
    if len(policy_hashes) != 1 or len(registry_hashes) != 1:
        raise ValueError("receipt requires one policy and one validator registry")
    ordered_decisions = tuple(sorted(decisions, key=lambda d: d.candidate_ids))
    counts = {
        DecisionStatus.ACCEPT: 0,
        DecisionStatus.ABSTAIN: 0,
        DecisionStatus.QUARANTINE: 0,
        DecisionStatus.REJECT: 0,
    }
    for decision in ordered_decisions:
        counts[decision.status] += 1
    lane_counts = {
        "ENTITY": sum(c.kind is CandidateKind.ENTITY for c in ordered_candidates),
        "NUMERIC": sum(c.kind is CandidateKind.NUMERIC for c in ordered_candidates),
        "VALIDATION": len(ordered_candidates),
    }
    unsigned = {
        "coordination_id": coordination_id,
        "arbiter_version": arbiter_version,
        "input_manifest_sha256": input_manifest_sha256,
        "policy_sha256": next(iter(policy_hashes)),
        "validator_registry_sha256": next(iter(registry_hashes)),
        "candidate_count_by_lane": lane_counts,
        "accepted_count": counts[DecisionStatus.ACCEPT],
        "abstained_count": counts[DecisionStatus.ABSTAIN],
        "quarantined_count": counts[DecisionStatus.QUARANTINE],
        "rejected_count": counts[DecisionStatus.REJECT],
        "decisions": [d.to_dict() for d in ordered_decisions],
        "external_cost_usd": format(external_cost_usd, "f"),
        "production_writes": production_writes,
        "claim_limit": claim_limit,
        "next_gate": next_gate,
    }
    replay_digest = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
    return Receipt(
        coordination_id=coordination_id,
        arbiter_version=arbiter_version,
        input_manifest_sha256=input_manifest_sha256,
        policy_sha256=next(iter(policy_hashes)),
        validator_registry_sha256=next(iter(registry_hashes)),
        candidate_count_by_lane=lane_counts,
        accepted_count=counts[DecisionStatus.ACCEPT],
        abstained_count=counts[DecisionStatus.ABSTAIN],
        quarantined_count=counts[DecisionStatus.QUARANTINE],
        rejected_count=counts[DecisionStatus.REJECT],
        decisions=ordered_decisions,
        external_cost_usd=external_cost_usd,
        production_writes=production_writes,
        claim_limit=claim_limit,
        next_gate=next_gate,
        replay_digest=replay_digest,
    )


def _candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    payload = dataclasses.asdict(candidate)
    payload["kind"] = candidate.kind.value
    payload["evidence_channel"] = candidate.evidence_channel.value
    payload["semantic_class"] = candidate.semantic_class.value if candidate.semantic_class else None
    payload["trust"] = dataclasses.asdict(candidate.trust)
    payload["word_ids"] = list(candidate.word_ids)
    return payload


def receipt_json(receipt: Receipt) -> str:
    return canonical_json(receipt.to_dict()) + "\n"
