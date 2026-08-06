from __future__ import annotations

import hashlib
import json
import unittest

from evidence_scope import (
    ChannelValidation,
    ClaimRequirement,
    ClaimScope,
    EvidenceBundle,
    EvidenceChannel,
    ResolutionState,
    evaluate_bundle,
)

POLICY_SHA256 = hashlib.sha256(b"stage07-policy-v9").hexdigest()
VALIDATOR_ID = "validator:test:stage07"


def validations(
    observations: dict[EvidenceChannel, str],
    *channels: EvidenceChannel,
) -> dict[EvidenceChannel, ChannelValidation]:
    return {
        channel: ChannelValidation.issue(
            channel=channel,
            observation=observations[channel],
            validator_id=VALIDATOR_ID,
            policy_sha256=POLICY_SHA256,
        )
        for channel in channels
    }


def bundle(
    observations: dict[EvidenceChannel, str],
    *,
    validated: tuple[EvidenceChannel, ...] = (),
    pages: tuple[int, ...] = (1,),
    total_pages: int = 1,
    partial: bool = False,
    integrity_ok: bool = True,
    integrity_reason: str = "INTEGRITY_OK",
) -> EvidenceBundle:
    return EvidenceBundle(
        observations=observations,
        channel_validations=validations(observations, *validated),
        processed_pages=pages,
        total_pages=total_pages,
        partial_document=partial,
        integrity_ok=integrity_ok,
        integrity_reason=integrity_reason,
    )


def requirement(
    claim_id: str,
    token: str,
    *,
    scope: ClaimScope = ClaimScope.DOCUMENT_CONTENT,
    hard: bool = True,
    confirmation: tuple[EvidenceChannel, ...] = (EvidenceChannel.OCR_CONTENT,),
    diagnostic: tuple[EvidenceChannel, ...] = (),
    metadata: tuple[EvidenceChannel, ...] = (),
) -> ClaimRequirement:
    return ClaimRequirement(
        claim_id=claim_id,
        scope=scope,
        tokens=(token,),
        confirmation_channels=confirmation,
        diagnostic_channels=diagnostic,
        metadata_channels=metadata,
        hard=hard,
    )


class EvidenceScopePolicyTests(unittest.TestCase):
    def test_source_provenance_confirms_publisher_without_ocr_literal(self) -> None:
        observations = {
            EvidenceChannel.SOURCE_PROVENANCE: "host:oncae.gob.hn publisher:ONCAE",
            EvidenceChannel.DOCUMENT_METADATA: "Guía para contratación directa SESAL agosto 2024",
            EvidenceChannel.OCR_CONTENT: "Guía para contratación directa del sistema de salud",
            EvidenceChannel.NATIVE_CONTROL: "Guía para contratación directa del sistema de salud",
        }
        result = evaluate_bundle(
            bundle(
                observations,
                validated=tuple(observations),
                pages=(1, 2, 3),
                total_pages=27,
                partial=True,
            ),
            [
                requirement(
                    "publisher_oncae",
                    "ONCAE",
                    scope=ClaimScope.SOURCE_IDENTITY,
                    confirmation=(EvidenceChannel.SOURCE_PROVENANCE,),
                )
            ],
        )
        self.assertEqual(result.verdict, "PASS_SCOPED")
        self.assertEqual(result.claims[0].state, ResolutionState.MATCH_OFFICIAL)

    def test_unvalidated_provenance_cannot_confirm_official_identity(self) -> None:
        observations = {EvidenceChannel.SOURCE_PROVENANCE: "publisher:ONCAE"}
        result = evaluate_bundle(
            bundle(observations),
            [
                requirement(
                    "publisher_oncae",
                    "ONCAE",
                    scope=ClaimScope.SOURCE_IDENTITY,
                    confirmation=(EvidenceChannel.SOURCE_PROVENANCE,),
                )
            ],
        )
        claim = result.claims[0]
        self.assertEqual(result.verdict, "ABSTAIN")
        self.assertEqual(claim.state, ResolutionState.NOT_EVALUABLE)
        self.assertEqual(claim.reason_code, "EVIDENCE_CHANNEL_NOT_VALIDATED")
        self.assertEqual(
            claim.unvalidated_observed_channels,
            (EvidenceChannel.SOURCE_PROVENANCE,),
        )

    def test_forged_validation_receipt_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not bind"):
            ChannelValidation(
                channel=EvidenceChannel.OCR_CONTENT,
                observation_sha256=hashlib.sha256(b"PACC").hexdigest(),
                validator_id=VALIDATOR_ID,
                policy_sha256=POLICY_SHA256,
                receipt_sha256="0" * 64,
            )

    def test_validation_must_bind_observed_text(self) -> None:
        validation = ChannelValidation.issue(
            channel=EvidenceChannel.OCR_CONTENT,
            observation="PACC",
            validator_id=VALIDATOR_ID,
            policy_sha256=POLICY_SHA256,
        )
        with self.assertRaisesRegex(ValueError, "does not bind the observed"):
            EvidenceBundle(
                observations={EvidenceChannel.OCR_CONTENT: "PACE"},
                channel_validations={EvidenceChannel.OCR_CONTENT: validation},
                processed_pages=(1,),
                total_pages=1,
                partial_document=False,
            )

    def test_bundle_snapshots_observations_and_validations(self) -> None:
        observations = {EvidenceChannel.OCR_CONTENT: "PACC"}
        validation_map = validations(observations, EvidenceChannel.OCR_CONTENT)
        frozen = EvidenceBundle(observations, validation_map, (1,), 1, False)
        req = requirement("pacc", "PACC")
        before = evaluate_bundle(frozen, [req]).canonical_json()
        observations[EvidenceChannel.OCR_CONTENT] = "PACE"
        validation_map.clear()
        self.assertEqual(before, evaluate_bundle(frozen, [req]).canonical_json())

    def test_metadata_cannot_be_configured_as_content_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "document_content cannot use"):
            requirement(
                "year_content",
                "2023",
                confirmation=(EvidenceChannel.DOCUMENT_METADATA,),
            )

    def test_source_provenance_cannot_confirm_document_content(self) -> None:
        with self.assertRaisesRegex(ValueError, "document_content cannot use"):
            requirement(
                "pacc_content",
                "PACC",
                confirmation=(EvidenceChannel.SOURCE_PROVENANCE,),
            )

    def test_normalized_duplicate_tokens_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique after normalization"):
            ClaimRequirement(
                claim_id="title",
                scope=ClaimScope.DOCUMENT_CONTENT,
                tokens=("BÁSICOS", "BASICOS"),
                confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                hard=True,
            )

    def test_metadata_only_sesal_is_candidate_not_content_identity(self) -> None:
        observations = {
            EvidenceChannel.SOURCE_PROVENANCE: "host:oncae.gob.hn publisher:ONCAE",
            EvidenceChannel.DOCUMENT_METADATA: "GUIA PARA CONTRATACION DIRECTA SESAL AGOSTO 2024",
            EvidenceChannel.OCR_CONTENT: "GUIA PARA CONTRATACION DIRECTA DEL SISTEMA DE SALUD",
            EvidenceChannel.NATIVE_CONTROL: "GUIA PARA CONTRATACION DIRECTA DEL SISTEMA DE SALUD",
        }
        result = evaluate_bundle(
            bundle(
                observations,
                validated=tuple(observations),
                pages=(1, 2, 3),
                total_pages=27,
                partial=True,
            ),
            [
                requirement(
                    "sesal_text_identity",
                    "SESAL",
                    hard=False,
                    diagnostic=(EvidenceChannel.NATIVE_CONTROL,),
                    metadata=(EvidenceChannel.DOCUMENT_METADATA,),
                )
            ],
        )
        claim = result.claims[0]
        self.assertEqual(result.verdict, "PASS_SCOPED")
        self.assertEqual(claim.state, ResolutionState.CANDIDATE_REVIEW)
        self.assertEqual(claim.reason_code, "METADATA_ONLY_NOT_CONTENT_IDENTITY")

    def test_native_token_missing_from_ocr_quarantines_candidate(self) -> None:
        observations = {
            EvidenceChannel.DOCUMENT_METADATA: "GUIA DE REGISTROS Y FLUJO DE PACC 2023",
            EvidenceChannel.OCR_CONTENT: "DIAGRAMAS DE FLUJO DEL PACE",
            EvidenceChannel.NATIVE_CONTROL: "DIAGRAMAS DE FLUJO DEL PACC",
        }
        result = evaluate_bundle(
            bundle(
                observations,
                validated=tuple(observations),
                pages=(1, 2, 3),
                total_pages=15,
                partial=True,
            ),
            [
                requirement(
                    "pacc_content",
                    "PACC",
                    diagnostic=(EvidenceChannel.NATIVE_CONTROL,),
                    metadata=(EvidenceChannel.DOCUMENT_METADATA,),
                )
            ],
        )
        claim = result.claims[0]
        self.assertEqual(result.verdict, "QUARANTINED")
        self.assertEqual(claim.state, ResolutionState.QUARANTINED)
        self.assertEqual(claim.reason_code, "OCR_REQUIRED_TOKEN_MISSED")

    def test_partial_document_year_metadata_abstains_instead_of_failing_ocr(self) -> None:
        observations = {
            EvidenceChannel.DOCUMENT_METADATA: "CONCEPTOS BASICOS PACC ONCAE 2023",
            EvidenceChannel.OCR_CONTENT: "CONCEPTOS BASICOS PACC",
            EvidenceChannel.NATIVE_CONTROL: "CONCEPTOS BASICOS PACC",
        }
        result = evaluate_bundle(
            bundle(
                observations,
                validated=tuple(observations),
                pages=(1, 2, 3),
                total_pages=22,
                partial=True,
            ),
            [
                requirement(
                    "year_2023_content",
                    "2023",
                    diagnostic=(EvidenceChannel.NATIVE_CONTROL,),
                    metadata=(EvidenceChannel.DOCUMENT_METADATA,),
                )
            ],
        )
        claim = result.claims[0]
        self.assertEqual(result.verdict, "ABSTAIN")
        self.assertEqual(claim.state, ResolutionState.NOT_EVALUABLE)
        self.assertEqual(claim.reason_code, "PARTIAL_SCOPE_NOT_COVERED")

    def test_full_document_metadata_only_claim_is_not_confirmed(self) -> None:
        observations = {
            EvidenceChannel.DOCUMENT_METADATA: "CONCEPTOS BASICOS PACC ONCAE 2023",
            EvidenceChannel.OCR_CONTENT: "CONCEPTOS BASICOS PACC",
            EvidenceChannel.NATIVE_CONTROL: "CONCEPTOS BASICOS PACC",
        }
        result = evaluate_bundle(
            bundle(
                observations,
                validated=tuple(observations),
                pages=tuple(range(1, 23)),
                total_pages=22,
            ),
            [
                requirement(
                    "year_2023_content",
                    "2023",
                    diagnostic=(EvidenceChannel.NATIVE_CONTROL,),
                    metadata=(EvidenceChannel.DOCUMENT_METADATA,),
                )
            ],
        )
        claim = result.claims[0]
        self.assertEqual(result.verdict, "ABSTAIN")
        self.assertEqual(claim.state, ResolutionState.CANDIDATE_REVIEW)
        self.assertEqual(claim.reason_code, "METADATA_ONLY_NOT_CONTENT_IDENTITY")

    def test_all_hard_claims_confirmed_pass_scoped(self) -> None:
        observations = {
            EvidenceChannel.SOURCE_PROVENANCE: "host:oncae.gob.hn publisher:ONCAE",
            EvidenceChannel.OCR_CONTENT: "CONCEPTOS BASICOS PACC 2023",
            EvidenceChannel.NATIVE_CONTROL: "CONCEPTOS BASICOS PACC 2023",
        }
        result = evaluate_bundle(
            bundle(
                observations,
                validated=tuple(observations),
                pages=(1, 2, 3),
                total_pages=3,
            ),
            [
                requirement(
                    "publisher_oncae",
                    "ONCAE",
                    scope=ClaimScope.SOURCE_IDENTITY,
                    confirmation=(EvidenceChannel.SOURCE_PROVENANCE,),
                ),
                requirement(
                    "pacc",
                    "PACC",
                    diagnostic=(EvidenceChannel.NATIVE_CONTROL,),
                ),
                requirement(
                    "year_2023",
                    "2023",
                    diagnostic=(EvidenceChannel.NATIVE_CONTROL,),
                ),
            ],
        )
        self.assertEqual(result.verdict, "PASS_SCOPED")
        self.assertEqual(
            [claim.state for claim in result.claims],
            [
                ResolutionState.MATCH_OFFICIAL,
                ResolutionState.MATCH_VALIDATED,
                ResolutionState.MATCH_VALIDATED,
            ],
        )
        self.assertEqual(len(result.channel_validations), 3)

    def test_integrity_failure_quarantines_every_claim(self) -> None:
        observations = {EvidenceChannel.OCR_CONTENT: "PACC 2023"}
        result = evaluate_bundle(
            bundle(
                observations,
                validated=tuple(observations),
                integrity_ok=False,
                integrity_reason="LINEAGE_HASH_MISMATCH",
            ),
            [requirement("pacc", "PACC")],
        )
        self.assertEqual(result.verdict, "QUARANTINED")
        self.assertEqual(result.claims[0].reason_code, "LINEAGE_HASH_MISMATCH")

    def test_receipt_serialization_is_deterministic(self) -> None:
        observations_a = {
            EvidenceChannel.SOURCE_PROVENANCE: "publisher:ONCAE host:oncae.gob.hn",
            EvidenceChannel.OCR_CONTENT: "PACC",
        }
        observations_b = {
            EvidenceChannel.OCR_CONTENT: "PACC",
            EvidenceChannel.SOURCE_PROVENANCE: "publisher:ONCAE host:oncae.gob.hn",
        }
        requirements = [
            requirement(
                "publisher",
                "ONCAE",
                scope=ClaimScope.SOURCE_IDENTITY,
                confirmation=(EvidenceChannel.SOURCE_PROVENANCE,),
            ),
            requirement("pacc", "PACC"),
        ]
        first = evaluate_bundle(
            bundle(observations_a, validated=tuple(observations_a)),
            requirements,
        ).canonical_json()
        second = evaluate_bundle(
            bundle(observations_b, validated=tuple(observations_b)),
            requirements,
        ).canonical_json()
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertEqual(parsed["verdict"], "PASS_SCOPED")
        self.assertEqual(
            parsed["schema"], "data-science-pipeline/evidence-scope-receipt/3"
        )
        for validation in parsed["channel_validations"].values():
            self.assertEqual(
                validation["schema"],
                "data-science-pipeline/channel-validation/1",
            )


if __name__ == "__main__":
    unittest.main()
