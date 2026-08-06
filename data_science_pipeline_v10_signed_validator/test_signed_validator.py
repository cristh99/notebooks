from __future__ import annotations

import hashlib
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from evidence_scope import (
    ChannelValidation,
    ClaimRequirement,
    ClaimScope,
    EvidenceBundle,
    EvidenceChannel,
    ResolutionState,
    evaluate_bundle,
)
from signed_validator import (
    SignedChannelValidation,
    TrustEntry,
    TrustRegistry,
    authorize_validations,
)

POLICY_A = hashlib.sha256(b"policy-a").hexdigest()
POLICY_B = hashlib.sha256(b"policy-b").hexdigest()
SEED_A = bytes(range(32))
SEED_B = bytes(reversed(range(32)))


def keypair(seed: bytes):
    private = Ed25519PrivateKey.from_private_bytes(seed)
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, public


class SignedValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_a, public_a = keypair(SEED_A)
        self.private_b, public_b = keypair(SEED_B)
        self.entry_a = TrustEntry(
            validator_id="validator:oncae:01",
            public_key_raw=public_a,
            allowed_policy_sha256=(POLICY_A,),
            allowed_channels=(
                EvidenceChannel.SOURCE_PROVENANCE,
                EvidenceChannel.OCR_CONTENT,
            ),
        )
        self.registry = TrustRegistry((self.entry_a,))

    def validation(self, channel: EvidenceChannel, observation: str) -> ChannelValidation:
        return ChannelValidation.issue(
            channel=channel,
            observation=observation,
            validator_id=self.entry_a.validator_id,
            policy_sha256=POLICY_A,
        )

    def signed(self, channel: EvidenceChannel, observation: str) -> SignedChannelValidation:
        return SignedChannelValidation.sign(
            validation=self.validation(channel, observation),
            private_key=self.private_a,
            registry_sha256=self.registry.sha256(),
        )

    def test_valid_signature_authorizes_channel(self) -> None:
        signed = self.signed(EvidenceChannel.OCR_CONTENT, "PACC")
        authorized = authorize_validations(
            {EvidenceChannel.OCR_CONTENT: signed},
            registry=self.registry,
            expected_registry_sha256=self.registry.sha256(),
        )
        self.assertEqual(authorized[EvidenceChannel.OCR_CONTENT], signed.validation)

    def test_forged_signature_is_rejected(self) -> None:
        signed = self.signed(EvidenceChannel.OCR_CONTENT, "PACC")
        forged = signed.with_signature(b"\x00" * 64)
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            authorize_validations(
                {EvidenceChannel.OCR_CONTENT: forged},
                registry=self.registry,
                expected_registry_sha256=self.registry.sha256(),
            )

    def test_cross_validator_signature_is_rejected(self) -> None:
        validation = self.validation(EvidenceChannel.OCR_CONTENT, "PACC")
        signed = SignedChannelValidation.sign(
            validation=validation,
            private_key=self.private_b,
            registry_sha256=self.registry.sha256(),
        )
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            authorize_validations(
                {EvidenceChannel.OCR_CONTENT: signed},
                registry=self.registry,
                expected_registry_sha256=self.registry.sha256(),
            )

    def test_untrusted_validator_is_rejected(self) -> None:
        validation = ChannelValidation.issue(
            channel=EvidenceChannel.OCR_CONTENT,
            observation="PACC",
            validator_id="validator:unknown",
            policy_sha256=POLICY_A,
        )
        signed = SignedChannelValidation.sign(
            validation=validation,
            private_key=self.private_b,
            registry_sha256=self.registry.sha256(),
        )
        with self.assertRaisesRegex(ValueError, "validator is not trusted"):
            authorize_validations(
                {EvidenceChannel.OCR_CONTENT: signed},
                registry=self.registry,
                expected_registry_sha256=self.registry.sha256(),
            )

    def test_policy_not_allowed_is_rejected(self) -> None:
        validation = ChannelValidation.issue(
            channel=EvidenceChannel.OCR_CONTENT,
            observation="PACC",
            validator_id=self.entry_a.validator_id,
            policy_sha256=POLICY_B,
        )
        signed = SignedChannelValidation.sign(
            validation=validation,
            private_key=self.private_a,
            registry_sha256=self.registry.sha256(),
        )
        with self.assertRaisesRegex(ValueError, "policy is not authorized"):
            authorize_validations(
                {EvidenceChannel.OCR_CONTENT: signed},
                registry=self.registry,
                expected_registry_sha256=self.registry.sha256(),
            )

    def test_channel_not_allowed_is_rejected(self) -> None:
        signed = self.signed(EvidenceChannel.DOCUMENT_METADATA, "PACC")
        with self.assertRaisesRegex(ValueError, "channel is not authorized"):
            authorize_validations(
                {EvidenceChannel.DOCUMENT_METADATA: signed},
                registry=self.registry,
                expected_registry_sha256=self.registry.sha256(),
            )

    def test_registry_hash_mismatch_is_rejected(self) -> None:
        signed = self.signed(EvidenceChannel.OCR_CONTENT, "PACC")
        with self.assertRaisesRegex(ValueError, "registry hash mismatch"):
            authorize_validations(
                {EvidenceChannel.OCR_CONTENT: signed},
                registry=self.registry,
                expected_registry_sha256="0" * 64,
            )

    def test_signed_payload_cannot_replay_on_another_channel(self) -> None:
        signed = self.signed(EvidenceChannel.OCR_CONTENT, "PACC")
        with self.assertRaisesRegex(ValueError, "mapping key"):
            authorize_validations(
                {EvidenceChannel.SOURCE_PROVENANCE: signed},
                registry=self.registry,
                expected_registry_sha256=self.registry.sha256(),
            )

    def test_registry_hash_is_order_independent(self) -> None:
        entry_b = TrustEntry(
            validator_id="validator:second",
            public_key_raw=self.private_b.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ),
            allowed_policy_sha256=(POLICY_B,),
            allowed_channels=(EvidenceChannel.NATIVE_CONTROL,),
        )
        self.assertEqual(
            TrustRegistry((self.entry_a, entry_b)).sha256(),
            TrustRegistry((entry_b, self.entry_a)).sha256(),
        )

    def test_duplicate_validator_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "validator_id values must be unique"):
            TrustRegistry((self.entry_a, self.entry_a))

    def test_duplicate_public_key_across_validator_ids_is_rejected(self) -> None:
        duplicate_key_entry = TrustEntry(
            validator_id="validator:alias",
            public_key_raw=self.entry_a.public_key_raw,
            allowed_policy_sha256=(POLICY_A,),
            allowed_channels=(EvidenceChannel.OCR_CONTENT,),
        )
        with self.assertRaisesRegex(ValueError, "public keys must be unique"):
            TrustRegistry((self.entry_a, duplicate_key_entry))

    def test_invalid_public_key_length_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "32 bytes"):
            TrustEntry(
                validator_id="validator:bad",
                public_key_raw=b"bad",
                allowed_policy_sha256=(POLICY_A,),
                allowed_channels=(EvidenceChannel.OCR_CONTENT,),
            )

    def test_tampered_observation_validation_is_rejected_before_signature(self) -> None:
        signed = self.signed(EvidenceChannel.OCR_CONTENT, "PACC")
        with self.assertRaisesRegex(ValueError, "does not bind the observed"):
            EvidenceBundle(
                observations={EvidenceChannel.OCR_CONTENT: "PACE"},
                channel_validations=authorize_validations(
                    {EvidenceChannel.OCR_CONTENT: signed},
                    registry=self.registry,
                    expected_registry_sha256=self.registry.sha256(),
                ),
                processed_pages=(1,),
                total_pages=1,
                partial_document=False,
            )

    def test_end_to_end_signed_validation_reaches_match_official(self) -> None:
        observation = "host:oncae.gob.hn publisher:ONCAE"
        signed = self.signed(EvidenceChannel.SOURCE_PROVENANCE, observation)
        authorized = authorize_validations(
            {EvidenceChannel.SOURCE_PROVENANCE: signed},
            registry=self.registry,
            expected_registry_sha256=self.registry.sha256(),
        )
        result = evaluate_bundle(
            EvidenceBundle(
                observations={EvidenceChannel.SOURCE_PROVENANCE: observation},
                channel_validations=authorized,
                processed_pages=(1,),
                total_pages=1,
                partial_document=False,
            ),
            [
                ClaimRequirement(
                    claim_id="publisher",
                    scope=ClaimScope.SOURCE_IDENTITY,
                    tokens=("ONCAE",),
                    confirmation_channels=(EvidenceChannel.SOURCE_PROVENANCE,),
                    hard=True,
                )
            ],
        )
        self.assertEqual(result.verdict, "PASS_SCOPED")
        self.assertEqual(result.claims[0].state, ResolutionState.MATCH_OFFICIAL)


if __name__ == "__main__":
    unittest.main()
