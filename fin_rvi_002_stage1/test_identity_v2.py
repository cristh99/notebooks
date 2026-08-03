from __future__ import annotations

import json
import unittest

from fin_rvi_002_stage1.identity_v2 import adjudicate_object_v2, compact_identity_pairs_v2
from fin_rvi_002_stage1.ocds import ReleaseSummary
from fin_rvi_002_stage1.run_stage1_v2 import _best_document, freeze_holdout_v2


class IdentityGrammarV2Tests(unittest.TestCase):
    def _summary(
        self,
        *,
        source: str,
        buyer_ids=(),
        buyer_names=(),
        text="",
        documents=(),
    ) -> ReleaseSummary:
        return ReleaseSummary(
            source=source,
            source_year=2024,
            ocid=f"{source}-ocid",
            release_id=f"{source}-release",
            buyer_ids=tuple(buyer_ids),
            buyer_names=tuple(buyer_names),
            supplier_ids=(),
            supplier_names=(),
            amounts=(100.0,),
            dates=("2024-01-01",),
            object_text=text,
            classifications=(),
            documents=tuple(documents),
            codes=(),
        )

    def test_sit_alias_and_contract_code_separate_sources(self) -> None:
        left = self._summary(
            source="ONCAE",
            buyer_names=(
                "SECRETARIA ESTADO DESPACHOS INFRAESTRUCTURA TRANSPORTE SIT",
            ),
            text="Contrato SIT-CO-057-2024 limpieza vial",
        )
        right = self._summary(
            source="SEFIN",
            buyer_ids=("HNDENG:411",),
            buyer_names=("SECRETARIA INFRAESTRUCTURA TRANSPORTE",),
            text="Pago contrato SIT-CO-057-2024",
        )
        left_keys = {key for key, _ in compact_identity_pairs_v2(left)}
        right_keys = {key for key, _ in compact_identity_pairs_v2(right)}
        self.assertTrue(left_keys & right_keys)

    def test_fhis_alias_and_project_code_separate_sources(self) -> None:
        left = self._summary(
            source="ONCAE",
            buyer_names=("SEDECOAS FHIS",),
            text="Reposición agua potable código 108877",
        )
        right = self._summary(
            source="SEFIN",
            buyer_ids=("HNDENG:22",),
            buyer_names=("FONDO INVERSION SOCIAL",),
            text="Pago subproyecto 108877",
        )
        left_keys = {key for key, _ in compact_identity_pairs_v2(left)}
        right_keys = {key for key, _ in compact_identity_pairs_v2(right)}
        self.assertTrue(left_keys & right_keys)

    def test_freeze_preserves_breadth_and_within_code_ambiguity(self) -> None:
        candidates = []
        for code_index in range(5):
            for pair_index in range(3):
                candidates.append(
                    {
                        "candidate_id": f"code-{code_index}-pair-{pair_index}",
                        "shared_code": f"CODE:SIT-CO-{code_index:03d}-2024",
                        "linkage_status": "AMBIGUOUS",
                        "cardinality_type": "ONE_ONCAE_TO_MANY_SEFIN",
                    }
                )
        first = freeze_holdout_v2(json.loads(json.dumps(candidates)), 8)
        second = freeze_holdout_v2(json.loads(json.dumps(candidates)), 8)
        self.assertEqual(
            [item["candidate_id"] for item in first],
            [item["candidate_id"] for item in second],
        )
        self.assertEqual(len(first), 8)
        self.assertGreaterEqual(len({item["shared_code"] for item in first}), 4)
        self.assertIn(
            "WITHIN_CODE_AMBIGUITY",
            {item["holdout_stratum"] for item in first},
        )

    def test_document_selector_prefers_signed_contract(self) -> None:
        left = self._summary(
            source="ONCAE",
            buyer_names=("SIT",),
            text="Contrato SIT-CO-001-2024",
            documents=(
                {
                    "url": "https://example.test/tender.pdf",
                    "title": "Aviso",
                    "description": "",
                    "documentType": "tenderNotice",
                },
                {
                    "url": "https://example.test/contract.pdf",
                    "title": "Contrato",
                    "description": "",
                    "documentType": "contractSigned",
                },
            ),
        )
        right = self._summary(
            source="SEFIN",
            buyer_ids=("HNDENG:411",),
            text="Pago SIT-CO-001-2024",
        )
        selected = _best_document(left, right)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["documentType"], "contractSigned")

    def test_supplier_and_dense_shared_object_override_soft_lexicon_gap(self) -> None:
        left = ReleaseSummary(
            source="ONCAE", source_year=2024, ocid="l", release_id="l",
            buyer_ids=(), buyer_names=("SIT",),
            supplier_ids=("HNRTN:08019019129988",), supplier_names=("CONSTRUCTORA UNO",),
            amounts=(2989117.64,), dates=("2024-01-01",),
            object_text="Pavimentación con concreto hidráulico avenida principal aldea Cerro Grande Valle de Ángeles",
            classifications=(), documents=(), codes=("SIT-CO-324-2024",),
        )
        right = ReleaseSummary(
            source="SEFIN", source_year=2024, ocid="r", release_id="r",
            buyer_ids=("HNDENG:411",), buyer_names=("SIT",),
            supplier_ids=("HNRTN:HNRTN08019019129988",), supplier_names=("CONSTRUCTORA UNO",),
            amounts=(584268.0,), dates=("2024-12-24",),
            object_text="Pago estimación contrato SIT-CO-324-2024 construcción pavimentación concreto hidráulico avenida principal Cerro Grande Valle de Ángeles",
            classifications=(), documents=(), codes=("SIT-CO-324-2024",),
        )
        result = adjudicate_object_v2(left, right)
        self.assertEqual(result["decision"], "SUPPORTED")
        self.assertEqual(result["reason"], "SUPPLIER_AND_OBJECT_EVIDENCE_COMPATIBLE")

    def test_supplier_match_does_not_override_hard_hardware_software_conflict(self) -> None:
        left = ReleaseSummary(
            source="ONCAE", source_year=2024, ocid="l", release_id="l",
            buyer_ids=(), buyer_names=("SIT",),
            supplier_ids=("HNRTN:1",), supplier_names=("PROVEEDOR",),
            amounts=(100.0,), dates=("2024-01-01",),
            object_text="Compra de impresoras y tabletas", classifications=(), documents=(), codes=("SIT-SU-001-2024",),
        )
        right = ReleaseSummary(
            source="SEFIN", source_year=2024, ocid="r", release_id="r",
            buyer_ids=("HNDENG:411",), buyer_names=("SIT",),
            supplier_ids=("HNRTN:HNRTN1",), supplier_names=("PROVEEDOR",),
            amounts=(100.0,), dates=("2024-01-02",),
            object_text="Pago de licencias Adobe Acrobat y Photoshop", classifications=(), documents=(), codes=("SIT-SU-001-2024",),
        )
        result = adjudicate_object_v2(left, right)
        self.assertEqual(result["decision"], "REJECTED")
        self.assertTrue(result["hard_category_conflict"])


if __name__ == "__main__":
    unittest.main()
