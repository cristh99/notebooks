from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from evidence_scope import ChannelValidation, EvidenceChannel, canonical_bytes

SIGNED_SCHEMA = "data-science-pipeline/signed-channel-validation/1"
REGISTRY_SCHEMA = "data-science-pipeline/validator-trust-registry/1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class TrustEntry:
    validator_id: str
    public_key_raw: bytes
    allowed_policy_sha256: tuple[str, ...]
    allowed_channels: tuple[EvidenceChannel, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.validator_id, str) or not self.validator_id.strip():
            raise ValueError("validator_id must not be blank")
        if self.validator_id != self.validator_id.strip():
            raise ValueError("validator_id must be canonical without outer whitespace")
        public_key = bytes(self.public_key_raw)
        if len(public_key) != 32:
            raise ValueError("Ed25519 public_key_raw must be exactly 32 bytes")
        policies = tuple(sorted(set(self.allowed_policy_sha256)))
        channels = tuple(sorted(set(self.allowed_channels), key=lambda item: item.value))
        if not policies:
            raise ValueError("allowed_policy_sha256 must not be empty")
        if not channels:
            raise ValueError("allowed_channels must not be empty")
        for policy in policies:
            _require_sha256(policy, "allowed policy")
        if any(not isinstance(channel, EvidenceChannel) for channel in channels):
            raise TypeError("allowed_channels must contain EvidenceChannel values")
        object.__setattr__(self, "public_key_raw", public_key)
        object.__setattr__(self, "allowed_policy_sha256", policies)
        object.__setattr__(self, "allowed_channels", channels)

    @property
    def public_key_sha256(self) -> str:
        return hashlib.sha256(self.public_key_raw).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "validator_id": self.validator_id,
            "public_key_raw_b64": base64.b64encode(self.public_key_raw).decode("ascii"),
            "public_key_sha256": self.public_key_sha256,
            "allowed_policy_sha256": list(self.allowed_policy_sha256),
            "allowed_channels": [channel.value for channel in self.allowed_channels],
        }


@dataclass(frozen=True)
class TrustRegistry:
    entries: tuple[TrustEntry, ...]

    def __post_init__(self) -> None:
        entries = tuple(sorted(self.entries, key=lambda item: item.validator_id))
        if not entries:
            raise ValueError("trust registry must not be empty")
        if any(not isinstance(entry, TrustEntry) for entry in entries):
            raise TypeError("entries must contain TrustEntry values")
        ids = [entry.validator_id for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("validator_id values must be unique")
        public_keys = [entry.public_key_sha256 for entry in entries]
        if len(public_keys) != len(set(public_keys)):
            raise ValueError("Ed25519 public keys must be unique across validator IDs")
        object.__setattr__(self, "entries", entries)

    def sha256(self) -> str:
        payload = {
            "schema": REGISTRY_SCHEMA,
            "entries": [entry.to_dict() for entry in self.entries],
        }
        return hashlib.sha256(canonical_bytes(payload)).hexdigest()

    def get(self, validator_id: str) -> TrustEntry | None:
        return next(
            (entry for entry in self.entries if entry.validator_id == validator_id),
            None,
        )


@dataclass(frozen=True)
class SignedChannelValidation:
    validation: ChannelValidation
    registry_sha256: str
    signature: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.validation, ChannelValidation):
            raise TypeError("validation must be a ChannelValidation")
        _require_sha256(self.registry_sha256, "registry_sha256")
        signature = bytes(self.signature)
        if len(signature) != 64:
            raise ValueError("Ed25519 signature must be exactly 64 bytes")
        object.__setattr__(self, "signature", signature)

    def signing_payload(self) -> bytes:
        return canonical_bytes(
            {
                "schema": SIGNED_SCHEMA,
                "registry_sha256": self.registry_sha256,
                "validation": self.validation.to_dict(),
            }
        )

    @classmethod
    def sign(
        cls,
        *,
        validation: ChannelValidation,
        private_key: Ed25519PrivateKey,
        registry_sha256: str,
    ) -> SignedChannelValidation:
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError("private_key must be an Ed25519PrivateKey")
        unsigned = cls(
            validation=validation,
            registry_sha256=registry_sha256,
            signature=b"\x00" * 64,
        )
        return cls(
            validation=validation,
            registry_sha256=registry_sha256,
            signature=private_key.sign(unsigned.signing_payload()),
        )

    def with_signature(self, signature: bytes) -> SignedChannelValidation:
        return SignedChannelValidation(
            validation=self.validation,
            registry_sha256=self.registry_sha256,
            signature=signature,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SIGNED_SCHEMA,
            "registry_sha256": self.registry_sha256,
            "validation": self.validation.to_dict(),
            "signature_b64": base64.b64encode(self.signature).decode("ascii"),
        }


def authorize_validations(
    signed_validations: Mapping[EvidenceChannel, SignedChannelValidation],
    *,
    registry: TrustRegistry,
    expected_registry_sha256: str,
) -> Mapping[EvidenceChannel, ChannelValidation]:
    if not isinstance(registry, TrustRegistry):
        raise TypeError("registry must be a TrustRegistry")
    _require_sha256(expected_registry_sha256, "expected_registry_sha256")
    actual_registry_sha256 = registry.sha256()
    if actual_registry_sha256 != expected_registry_sha256:
        raise ValueError("registry hash mismatch")

    authorized: dict[EvidenceChannel, ChannelValidation] = {}
    for channel, signed in signed_validations.items():
        if not isinstance(channel, EvidenceChannel):
            raise TypeError("signed validation mapping keys must be EvidenceChannel values")
        if not isinstance(signed, SignedChannelValidation):
            raise TypeError("signed validation values must be SignedChannelValidation")
        if signed.validation.channel is not channel:
            raise ValueError("signed validation channel does not match mapping key")
        if signed.registry_sha256 != expected_registry_sha256:
            raise ValueError("signed validation registry hash mismatch")

        entry = registry.get(signed.validation.validator_id)
        if entry is None:
            raise ValueError("validator is not trusted")
        if signed.validation.policy_sha256 not in entry.allowed_policy_sha256:
            raise ValueError("policy is not authorized for validator")
        if channel not in entry.allowed_channels:
            raise ValueError("channel is not authorized for validator")

        public_key = Ed25519PublicKey.from_public_bytes(entry.public_key_raw)
        try:
            public_key.verify(signed.signature, signed.signing_payload())
        except InvalidSignature as exc:
            raise ValueError("signature verification failed") from exc
        authorized[channel] = signed.validation

    return MappingProxyType(authorized)
