from __future__ import annotations

import unittest

from fin_rvi_002_stage1.known_gold import evaluate


class KnownGoldTests(unittest.TestCase):
    def test_publication_is_not_promoted_as_contract_payment(self) -> None:
        rows = [{
            "candidate_id": "publication",
            "shared_code": "CODE:SIT-GA-001-2024",
            "decision": "REJECTED",
            "object_text": "Pago a periódico por publicación de licitación SIT-GA-001-2024",
        }]
        result = evaluate(rows)
        self.assertEqual(result["matched_candidates"], 1)
        self.assertEqual(result["unsafe_overpromotions"], 0)
        self.assertTrue(result["gate_no_unsafe_overpromotion"])

    def test_unsafe_promotion_fails_closed(self) -> None:
        rows = [{
            "candidate_id": "unsafe",
            "shared_code": "CODE:SIT-CO-057-2024",
            "decision": "SUPPORTED",
            "object_text": "Pago a ORLY-B por pavimentación Agalteca El Mochito",
        }]
        result = evaluate(rows)
        self.assertEqual(result["unsafe_overpromotions"], 1)
        self.assertFalse(result["gate_no_unsafe_overpromotion"])

    def test_fhis_contractor_and_ancillary_events_are_separate(self) -> None:
        rows = [
            {
                "candidate_id": "contractor",
                "shared_code": "PROJECT:108877",
                "decision": "SUPPORTED",
                "object_text": "Primera estimación reposición agua potable 108877 LEMPIRA",
            },
            {
                "candidate_id": "ancillary",
                "shared_code": "PROJECT:108877",
                "decision": "REJECTED",
                "object_text": "Viático combustible visita técnica proyecto 108877",
            },
        ]
        result = evaluate(rows)
        self.assertEqual(result["matched_candidates"], 2)
        self.assertEqual(result["exact_agreements"], 2)
        self.assertEqual(result["unsafe_overpromotions"], 0)


if __name__ == "__main__":
    unittest.main()
