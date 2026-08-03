from __future__ import annotations

import json
import unittest

from fin_rvi_002_stage1.identity_v2 import compact_identity_pairs_v2
from fin_rvi_002_stage1.ocds import ReleaseSummary
from fin_rvi_002_stage1.run_stage1_v2 import freeze_holdout_v2


class IdentityGrammarV2Tests(unittest.TestCase):
    def _summary(
        self,
        *,
        source: str,
        buyer_ids=(),
        buyer_names=(),
        text="",
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
            documents=(),
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


if __name__ == "__main__":
    unittest.main()
