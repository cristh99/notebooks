from __future__ import annotations

import copy
import unittest

from fin_rvi_002_stage1.ocds import ReleaseSummary
from fin_rvi_002_stage3.run_stage3 import (
    evidence_label,
    freeze_stage3,
    policy_metrics,
    supplier_facts,
)


class Stage3Tests(unittest.TestCase):
    def summary(self, *, source: str, supplier_id: str, supplier_name: str, text: str):
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

    def test_freeze_is_deterministic_and_caps_codes(self):
        candidates = []
        for code_index in range(80):
            for pair_index in range(4):
                candidates.append(
                    {
                        "candidate_id": f"candidate-{code_index}-{pair_index}",
                        "shared_code": f"CODE:SIT-CO-{code_index:03d}-2025",
                        "cardinality_type": "ONE_ONCAE_TO_MANY_SEFIN",
                        "relative_amount_difference": 0.9,
                        "absolute_days": 300,
                        "oncae_release_pk": code_index,
                        "sefin_release_pk": code_index * 10 + pair_index,
                    }
                )
        first = freeze_stage3(copy.deepcopy(candidates), 120)
        second = freeze_stage3(copy.deepcopy(candidates), 120)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 120)
        counts = {}
        for row in first:
            counts[row["shared_code"]] = counts.get(row["shared_code"], 0) + 1
        self.assertLessEqual(max(counts.values()), 2)
        self.assertTrue(all(row["stage3_selection_blind"] for row in first))

    def test_numeric_identifier_conflict_is_rejected(self):
        left = self.summary(
            source="ONCAE",
            supplier_id="HNRTN:08019000000001",
            supplier_name="CONSTRUCTORA UNO",
            text="Construcción de puente principal",
        )
        right = self.summary(
            source="SEFIN",
            supplier_id="HNRTN:08019000000002",
            supplier_name="CONSTRUCTORA UNO",
            text="Pago contrato construcción de puente principal",
        )
        facts = supplier_facts(left, right)
        label = evidence_label(
            left,
            right,
            {"hard_category_conflict": False},
            "Contrato construcción puente CONSTRUCTORA UNO",
            facts,
        )
        self.assertTrue(facts["numeric_conflict"])
        self.assertEqual(label["label"], "REJECTED")

    def test_exact_id_payment_and_document_support_is_supported(self):
        left = self.summary(
            source="ONCAE",
            supplier_id="HNRTN:08019000000001",
            supplier_name="CONSTRUCTORA UNO",
            text="Pavimentación con concreto hidráulico avenida Cerro Grande Valle Ángeles",
        )
        right = self.summary(
            source="SEFIN",
            supplier_id="HNRTN:HNRTN08019000000001",
            supplier_name="CONSTRUCTORA UNO",
            text="Pago estimación pavimentación concreto hidráulico avenida Cerro Grande Valle Ángeles",
        )
        facts = supplier_facts(left, right)
        label = evidence_label(
            left,
            right,
            {"hard_category_conflict": False},
            "Contrato pavimentación concreto hidráulico avenida Cerro Grande Valle Ángeles CONSTRUCTORA UNO",
            facts,
        )
        self.assertTrue(facts["exact_numeric_support"])
        self.assertEqual(label["label"], "SUPPORTED")

    def test_insufficient_name_only_evidence_abstains(self):
        left = self.summary(
            source="ONCAE",
            supplier_id="RAW:X",
            supplier_name="SERVICIOS GENERALES",
            text="Mantenimiento de instalaciones",
        )
        right = self.summary(
            source="SEFIN",
            supplier_id="RAW:Y",
            supplier_name="SERVICIOS GENERALES",
            text="Pago mantenimiento",
        )
        facts = supplier_facts(left, right)
        label = evidence_label(left, right, {"hard_category_conflict": False}, "", facts)
        self.assertEqual(label["label"], "UNRESOLVED")

    def test_policy_metrics_are_fail_closed(self):
        rows = [
            {
                "label": "SUPPORTED",
                "baseline_supplier_support": True,
                "policy_decision": "SUPPORTED",
            },
            {
                "label": "REJECTED",
                "baseline_supplier_support": True,
                "policy_decision": "UNRESOLVED",
            },
            {
                "label": "UNRESOLVED",
                "baseline_supplier_support": True,
                "policy_decision": "SUPPORTED",
            },
        ]
        metrics = policy_metrics(rows)
        self.assertEqual(metrics["B1_CODE_SUPPLIER"]["unsafe_overpromotions"], 1)
        self.assertEqual(metrics["POLICY_DOCUMENTARY"]["unsafe_overpromotions"], 0)
        self.assertEqual(metrics["POLICY_DOCUMENTARY"]["supported_recovered"], 1)


if __name__ == "__main__":
    unittest.main()
