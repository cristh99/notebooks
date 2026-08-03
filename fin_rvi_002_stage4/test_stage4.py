from __future__ import annotations

import copy
import json
import unittest

from fin_rvi_002_stage1.ocds import ReleaseSummary
from fin_rvi_002_stage4.policy_v3 import adjudicate_policy_v3
from fin_rvi_002_stage4.run_stage4 import SEED, exclusion_manifest, freeze_stage4


class Stage4Tests(unittest.TestCase):
    def summary(
        self,
        *,
        source: str,
        supplier_id: str,
        supplier_name: str,
        text: str,
    ) -> ReleaseSummary:
        return ReleaseSummary(
            source=source,
            source_year=2025,
            ocid=f"{source}-ocid",
            release_id=f"{source}-release",
            buyer_ids=("HNDENG:411",),
            buyer_names=("SECRETARIA INFRAESTRUCTURA TRANSPORTE",),
            supplier_ids=(supplier_id,),
            supplier_names=(supplier_name,),
            amounts=(100.0,),
            dates=("2025-01-01",),
            object_text=text,
            classifications=(),
            documents=(),
            codes=("SIT-CO-999-2025",),
        )

    def test_numeric_conflict_veto(self) -> None:
        left = self.summary(
            source="ONCAE",
            supplier_id="HNRTN:08019000000001",
            supplier_name="CONSTRUCTORA UNO",
            text="Construcción puente principal SIT-CO-999-2025",
        )
        right = self.summary(
            source="SEFIN",
            supplier_id="HNRTN:08019000000002",
            supplier_name="CONSTRUCTORA UNO",
            text="Pago construcción puente principal SIT-CO-999-2025",
        )
        result = adjudicate_policy_v3(left, right)
        self.assertEqual(result["decision"], "REJECTED")
        self.assertEqual(result["reason"], "V3_NUMERIC_SUPPLIER_CONFLICT_VETO")

    def test_exact_id_rescue(self) -> None:
        left = self.summary(
            source="ONCAE",
            supplier_id="HNRTN:08019000000001",
            supplier_name="C C CONSTRUCCIONES",
            text="Remodelación baños infraestructura transporte SIT-CO-999-2025",
        )
        right = self.summary(
            source="SEFIN",
            supplier_id="HNRTN:HNRTN08019000000001",
            supplier_name="C C CONTRUCCIONES",
            text="Pago estimación remodelación baños infraestructura transporte SIT-CO-999-2025",
        )
        result = adjudicate_policy_v3(left, right)
        self.assertEqual(result["decision"], "SUPPORTED")
        self.assertEqual(result["reason"], "V3_EXACT_ID_PAYMENT_AND_OBJECT_SUPPORT")

    def test_stage3_codes_are_excluded(self) -> None:
        manifest = exclusion_manifest()
        excluded = manifest["shared_codes"][0]
        candidates = [
            {
                "candidate_id": "excluded",
                "shared_code": excluded,
                "cardinality_type": "ONE_TO_ONE",
                "relative_amount_difference": 0.01,
                "absolute_days": 10,
                "oncae_release_pk": 1,
                "sefin_release_pk": 2,
            }
        ]
        for index in range(250):
            candidates.append(
                {
                    "candidate_id": f"fresh-{index}",
                    "shared_code": f"CODE:SIT-CO-{800 + index:03d}-2026",
                    "cardinality_type": "ONE_TO_ONE",
                    "relative_amount_difference": 0.01,
                    "absolute_days": 10,
                    "oncae_release_pk": index + 10,
                    "sefin_release_pk": index + 1000,
                }
            )
        first = freeze_stage4(copy.deepcopy(candidates), 120)
        second = freeze_stage4(copy.deepcopy(candidates), 120)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 120)
        self.assertNotIn(excluded, {row["shared_code"] for row in first})
        self.assertTrue(all(row["stage4_selection_seed"] == SEED for row in first))

    def test_manifest_is_bound_to_stage3_artifact(self) -> None:
        manifest = exclusion_manifest()
        self.assertEqual(manifest["source_run_id"], 30840335568)
        self.assertEqual(manifest["source_artifact_id"], 8866730681)
        self.assertEqual(manifest["counts"]["shared_codes"], 118)
        self.assertEqual(len(manifest["shared_codes"]), 118)


if __name__ == "__main__":
    unittest.main()
