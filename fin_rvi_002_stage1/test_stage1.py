from __future__ import annotations

import json
import unittest

from fin_rvi_002_stage1.ocds import (
    ReleaseSummary,
    adjudicate_object,
    closest_amount,
    iter_releases,
    normalize_name,
    summarize_release,
)
from fin_rvi_002_stage1.run_stage1 import freeze_holdout


class OCDSStage1Tests(unittest.TestCase):
    def test_iter_release_package(self) -> None:
        package = {"releases": [{"ocid": "a"}, {"ocid": "b"}]}
        self.assertEqual([item["ocid"] for item in iter_releases(package)], ["a", "b"])

    def test_iter_record_package(self) -> None:
        package = {"records": [{"compiledRelease": {"ocid": "x"}}]}
        self.assertEqual([item["ocid"] for item in iter_releases(package)], ["x"])

    def test_name_normalization_removes_legal_noise(self) -> None:
        self.assertEqual(normalize_name("Servicios de Honduras, S. de R.L."), "SERVICIOS")

    def test_summary_extracts_buyer_supplier_transaction_and_object(self) -> None:
        release = {
            "ocid": "ocds-test-1",
            "id": "release-1",
            "date": "2025-01-02T00:00:00Z",
            "buyer": {"id": "HN-BUYER-1", "name": "Secretaría de Prueba"},
            "awards": [
                {
                    "id": "award-1",
                    "title": "Compra de impresoras",
                    "value": {"amount": 1000},
                    "suppliers": [
                        {
                            "name": "Proveedor S. de R.L.",
                            "identifier": {"scheme": "HN-RTN", "id": "0801-0000-000000"},
                        }
                    ],
                }
            ],
            "contracts": [
                {
                    "id": "SIT-GA-001-2025",
                    "dateSigned": "2025-01-10",
                    "implementation": {
                        "transactions": [
                            {
                                "id": "TRB-1",
                                "date": "2025-02-01",
                                "value": {"amount": 995},
                                "description": "Pago por impresoras",
                                "payee": {
                                    "name": "Proveedor",
                                    "identifier": {"scheme": "HN-RTN", "id": "08010000000000"},
                                },
                            }
                        ]
                    },
                }
            ],
        }
        summary = summarize_release(release, "ONCAE", 2025)
        self.assertIn("HNRTN:08010000000000", summary.supplier_ids)
        self.assertIn(1000.0, summary.amounts)
        self.assertIn(995.0, summary.amounts)
        self.assertIn("2025-01-10", summary.dates)
        self.assertIn("IMPRESORAS", summary.object_text.upper())

    def test_closest_amount(self) -> None:
        relative, left, right = closest_amount((100.0, 300.0), (105.0, 1000.0)) or (None, None, None)
        self.assertAlmostEqual(relative, 5 / 105)
        self.assertEqual((left, right), (100.0, 105.0))

    def test_object_conflict_rejects_hardware_vs_software(self) -> None:
        common = dict(
            source_year=2025,
            buyer_ids=("RAW:BUYER",),
            buyer_names=("BUYER",),
            supplier_ids=("HNRTN:1",),
            supplier_names=("SUPPLIER",),
            amounts=(100.0,),
            dates=("2025-01-01",),
            classifications=(),
            documents=(),
            codes=(),
        )
        left = ReleaseSummary(
            source="ONCAE",
            ocid="left",
            release_id="left-r",
            object_text="Compra de impresoras y tabletas para oficinas",
            **common,
        )
        right = ReleaseSummary(
            source="SEFIN",
            ocid="right",
            release_id="right-r",
            object_text="Pago de licencias Adobe Acrobat y Photoshop",
            **common,
        )
        result = adjudicate_object(left, right)
        self.assertEqual(result["decision"], "REJECTED")
        self.assertEqual(result["reason"], "MATERIAL_OBJECT_CATEGORY_CONFLICT")

    def test_object_supports_compatible_water_project(self) -> None:
        common = dict(
            source_year=2025,
            buyer_ids=("RAW:BUYER",),
            buyer_names=("BUYER",),
            supplier_ids=("HNRTN:1",),
            supplier_names=("SUPPLIER",),
            amounts=(100.0,),
            dates=("2025-01-01",),
            classifications=(),
            documents=(),
            codes=(),
        )
        left = ReleaseSummary(
            source="ONCAE",
            ocid="left",
            release_id="left-r",
            object_text="Reposición del sistema de agua potable El Marañón",
            **common,
        )
        right = ReleaseSummary(
            source="SEFIN",
            ocid="right",
            release_id="right-r",
            object_text="Primera estimación reposición sistema agua potable Marañón",
            **common,
        )
        result = adjudicate_object(left, right)
        self.assertEqual(result["decision"], "SUPPORTED")

    def test_holdout_is_deterministic_and_ignores_object_outcome(self) -> None:
        candidates = [
            {
                "candidate_id": f"c{i}",
                "linkage_status": "STRICT_1_TO_1",
                "secret_outcome": "REJECTED" if i % 2 else "SUPPORTED",
            }
            for i in range(30)
        ]
        first = freeze_holdout(json.loads(json.dumps(candidates)), 20)
        second = freeze_holdout(json.loads(json.dumps(candidates)), 20)
        self.assertEqual(
            [item["candidate_id"] for item in first],
            [item["candidate_id"] for item in second],
        )
        self.assertEqual(len(first), 20)


if __name__ == "__main__":
    unittest.main()
