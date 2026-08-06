from __future__ import annotations

import json
import unittest

from evidence_scope import (
    ClaimRequirement,
    EvidenceBundle,
    EvidenceChannel,
    ResolutionState,
    evaluate_bundle,
)


class EvidenceScopePolicyTests(unittest.TestCase):
    def test_source_provenance_confirms_publisher_without_ocr_literal(self) -> None:
        bundle = EvidenceBundle(
            observations={
                EvidenceChannel.SOURCE_PROVENANCE: "host:oncae.gob.hn publisher:ONCAE",
                EvidenceChannel.DOCUMENT_METADATA: "Guía para contratación directa SESAL agosto 2024",
                EvidenceChannel.OCR_CONTENT: "Guía para contratación directa del sistema de salud",
                EvidenceChannel.NATIVE_CONTROL: "Guía para contratación directa del sistema de salud",
            },
            processed_pages=(1, 2, 3),
            total_pages=27,
            partial_document=True,
        )
        result = evaluate_bundle(
            bundle,
            [
                ClaimRequirement(
                    claim_id="publisher_oncae",
                    tokens=("ONCAE",),
                    confirmation_channels=(EvidenceChannel.SOURCE_PROVENANCE,),
                    hard=True,
                )
            ],
        )
        self.assertEqual(result.verdict, "PASS_SCOPED")
        self.assertEqual(result.claims[0].state, ResolutionState.MATCH_OFFICIAL)

    def test_metadata_only_sesal_is_candidate_not_content_identity(self) -> None:
        bundle = EvidenceBundle(
            observations={
                EvidenceChannel.SOURCE_PROVENANCE: "host:oncae.gob.hn publisher:ONCAE",
                EvidenceChannel.DOCUMENT_METADATA: "GUIA PARA CONTRATACION DIRECTA SESAL AGOSTO 2024",
                EvidenceChannel.OCR_CONTENT: "GUIA PARA CONTRATACION DIRECTA DEL SISTEMA DE SALUD",
                EvidenceChannel.NATIVE_CONTROL: "GUIA PARA CONTRATACION DIRECTA DEL SISTEMA DE SALUD",
            },
            processed_pages=(1, 2, 3),
            total_pages=27,
            partial_document=True,
        )
        result = evaluate_bundle(
            bundle,
            [
                ClaimRequirement(
                    claim_id="sesal_text_identity",
                    tokens=("SESAL",),
                    confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                    diagnostic_channels=(EvidenceChannel.NATIVE_CONTROL,),
                    metadata_channels=(EvidenceChannel.DOCUMENT_METADATA,),
                    hard=False,
                )
            ],
        )
        self.assertEqual(result.verdict, "PASS_SCOPED")
        self.assertEqual(result.claims[0].state, ResolutionState.CANDIDATE_REVIEW)
        self.assertEqual(result.claims[0].reason_code, "METADATA_ONLY_NOT_CONTENT_IDENTITY")

    def test_native_token_missing_from_ocr_quarantines_candidate(self) -> None:
        bundle = EvidenceBundle(
            observations={
                EvidenceChannel.DOCUMENT_METADATA: "GUIA DE REGISTROS Y FLUJO DE PACC 2023",
                EvidenceChannel.OCR_CONTENT: "DIAGRAMAS DE FLUJO DEL PACE",
                EvidenceChannel.NATIVE_CONTROL: "DIAGRAMAS DE FLUJO DEL PACC",
            },
            processed_pages=(1, 2, 3),
            total_pages=15,
            partial_document=True,
        )
        result = evaluate_bundle(
            bundle,
            [
                ClaimRequirement(
                    claim_id="pacc_content",
                    tokens=("PACC",),
                    confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                    diagnostic_channels=(EvidenceChannel.NATIVE_CONTROL,),
                    metadata_channels=(EvidenceChannel.DOCUMENT_METADATA,),
                    hard=True,
                )
            ],
        )
        self.assertEqual(result.verdict, "QUARANTINED")
        self.assertEqual(result.claims[0].state, ResolutionState.QUARANTINED)
        self.assertEqual(result.claims[0].reason_code, "OCR_REQUIRED_TOKEN_MISSED")

    def test_partial_document_year_metadata_abstains_instead_of_failing_ocr(self) -> None:
        bundle = EvidenceBundle(
            observations={
                EvidenceChannel.DOCUMENT_METADATA: "CONCEPTOS BASICOS PACC ONCAE 2023",
                EvidenceChannel.OCR_CONTENT: "CONCEPTOS BASICOS PACC",
                EvidenceChannel.NATIVE_CONTROL: "CONCEPTOS BASICOS PACC",
            },
            processed_pages=(1, 2, 3),
            total_pages=22,
            partial_document=True,
        )
        result = evaluate_bundle(
            bundle,
            [
                ClaimRequirement(
                    claim_id="year_2023_content",
                    tokens=("2023",),
                    confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                    diagnostic_channels=(EvidenceChannel.NATIVE_CONTROL,),
                    metadata_channels=(EvidenceChannel.DOCUMENT_METADATA,),
                    hard=True,
                )
            ],
        )
        self.assertEqual(result.verdict, "ABSTAIN")
        self.assertEqual(result.claims[0].state, ResolutionState.NOT_EVALUABLE)
        self.assertEqual(result.claims[0].reason_code, "PARTIAL_SCOPE_NOT_COVERED")

    def test_full_document_metadata_only_claim_is_not_confirmed(self) -> None:
        bundle = EvidenceBundle(
            observations={
                EvidenceChannel.DOCUMENT_METADATA: "CONCEPTOS BASICOS PACC ONCAE 2023",
                EvidenceChannel.OCR_CONTENT: "CONCEPTOS BASICOS PACC",
                EvidenceChannel.NATIVE_CONTROL: "CONCEPTOS BASICOS PACC",
            },
            processed_pages=tuple(range(1, 23)),
            total_pages=22,
            partial_document=False,
        )
        result = evaluate_bundle(
            bundle,
            [
                ClaimRequirement(
                    claim_id="year_2023_content",
                    tokens=("2023",),
                    confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                    diagnostic_channels=(EvidenceChannel.NATIVE_CONTROL,),
                    metadata_channels=(EvidenceChannel.DOCUMENT_METADATA,),
                    hard=True,
                )
            ],
        )
        self.assertEqual(result.verdict, "ABSTAIN")
        self.assertEqual(result.claims[0].state, ResolutionState.CANDIDATE_REVIEW)
        self.assertEqual(result.claims[0].reason_code, "METADATA_ONLY_NOT_CONTENT_IDENTITY")

    def test_all_hard_claims_confirmed_pass_scoped(self) -> None:
        bundle = EvidenceBundle(
            observations={
                EvidenceChannel.SOURCE_PROVENANCE: "host:oncae.gob.hn publisher:ONCAE",
                EvidenceChannel.OCR_CONTENT: "CONCEPTOS BASICOS PACC 2023",
                EvidenceChannel.NATIVE_CONTROL: "CONCEPTOS BASICOS PACC 2023",
            },
            processed_pages=(1, 2, 3),
            total_pages=3,
            partial_document=False,
        )
        result = evaluate_bundle(
            bundle,
            [
                ClaimRequirement(
                    claim_id="publisher_oncae",
                    tokens=("ONCAE",),
                    confirmation_channels=(EvidenceChannel.SOURCE_PROVENANCE,),
                    hard=True,
                ),
                ClaimRequirement(
                    claim_id="pacc",
                    tokens=("PACC",),
                    confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                    diagnostic_channels=(EvidenceChannel.NATIVE_CONTROL,),
                    hard=True,
                ),
                ClaimRequirement(
                    claim_id="year_2023",
                    tokens=("2023",),
                    confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                    diagnostic_channels=(EvidenceChannel.NATIVE_CONTROL,),
                    hard=True,
                ),
            ],
        )
        self.assertEqual(result.verdict, "PASS_SCOPED")
        self.assertEqual([claim.state for claim in result.claims], [
            ResolutionState.MATCH_OFFICIAL,
            ResolutionState.MATCH_VALIDATED,
            ResolutionState.MATCH_VALIDATED,
        ])

    def test_integrity_failure_quarantines_every_claim(self) -> None:
        bundle = EvidenceBundle(
            observations={EvidenceChannel.OCR_CONTENT: "PACC 2023"},
            processed_pages=(1,),
            total_pages=1,
            partial_document=False,
            integrity_ok=False,
            integrity_reason="LINEAGE_HASH_MISMATCH",
        )
        result = evaluate_bundle(
            bundle,
            [
                ClaimRequirement(
                    claim_id="pacc",
                    tokens=("PACC",),
                    confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                    hard=True,
                )
            ],
        )
        self.assertEqual(result.verdict, "QUARANTINED")
        self.assertEqual(result.claims[0].reason_code, "LINEAGE_HASH_MISMATCH")

    def test_receipt_serialization_is_deterministic(self) -> None:
        bundle = EvidenceBundle(
            observations={
                EvidenceChannel.SOURCE_PROVENANCE: "publisher:ONCAE host:oncae.gob.hn",
                EvidenceChannel.OCR_CONTENT: "PACC",
            },
            processed_pages=(1,),
            total_pages=1,
            partial_document=False,
        )
        requirements = [
            ClaimRequirement(
                claim_id="publisher",
                tokens=("ONCAE",),
                confirmation_channels=(EvidenceChannel.SOURCE_PROVENANCE,),
                hard=True,
            ),
            ClaimRequirement(
                claim_id="pacc",
                tokens=("PACC",),
                confirmation_channels=(EvidenceChannel.OCR_CONTENT,),
                hard=True,
            ),
        ]
        first = evaluate_bundle(bundle, requirements).canonical_json()
        second = evaluate_bundle(bundle, list(reversed(list(reversed(requirements))))).canonical_json()
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertEqual(parsed["verdict"], "PASS_SCOPED")
        self.assertEqual(parsed["schema"], "data-science-pipeline/evidence-scope-receipt/1")


if __name__ == "__main__":
    unittest.main()
