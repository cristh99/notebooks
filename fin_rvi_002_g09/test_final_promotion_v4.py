from __future__ import annotations

import copy
import unittest

from fin_rvi_002_g09.verify_final_promotion_v4 import (
    EXPECTED_LABEL_COUNTS,
    EXPECTED_METRICS,
    EXPECTED_READOUT,
    EXPECTED_REPLAY,
    _verify_stage7_receipt,
    digest,
)


class FinalPromotionV4Tests(unittest.TestCase):
    def receipt(self, *, node: bool) -> dict:
        replay = {
            "compact_file_sha256": EXPECTED_REPLAY["compact_file_sha256"],
            "labels_file_sha256": EXPECTED_REPLAY["labels_file_sha256"],
            "exclusion_manifest_file_sha256": EXPECTED_REPLAY[
                "exclusion_manifest_file_sha256"
            ],
            "candidate_ids_sha256": EXPECTED_REPLAY["candidate_ids_sha256"],
            (
                "independent_policy_decisions_sha256"
                if node
                else "independent_node_policy_decisions_sha256"
            ): EXPECTED_REPLAY["independent_policy_decisions_sha256"],
        }
        payload = {
            "schema": (
                "fin-rvi-002/stage7-node-clean-reconstruction/1"
                if node
                else "fin-rvi-002/stage7-clean-reconstruction/1"
            ),
            "gates": {"all_exact": True, "tamper_rejected": True},
            "label_counts": EXPECTED_LABEL_COUNTS,
            "policy_metrics": EXPECTED_METRICS,
            "gate_readout": {
                "G07": "PASS",
                "G09_REPLICATION": "PASS",
                "G09": "OPEN_FINAL_CONTRACT_PROMOTION_REQUIRED",
                "finance_score": 920,
            },
            "replay": replay,
        }
        return {"payload": payload, "sha256": digest(payload)}

    def test_python_and_node_stage7_receipts_are_accepted(self):
        py = self.receipt(node=False)
        node = self.receipt(node=True)
        self.assertEqual(
            _verify_stage7_receipt(
                py, "fin-rvi-002/stage7-clean-reconstruction/1", False
            ),
            [],
        )
        self.assertEqual(
            _verify_stage7_receipt(
                node, "fin-rvi-002/stage7-node-clean-reconstruction/1", True
            ),
            [],
        )

    def test_semantically_rehashed_unsafe_receipt_is_rejected(self):
        forged = self.receipt(node=False)
        forged["payload"]["policy_metrics"]["POLICY_DOCUMENTARY"][
            "unsafe_overpromotions"
        ] = 1
        forged["sha256"] = digest(forged["payload"])
        errors = _verify_stage7_receipt(
            forged, "fin-rvi-002/stage7-clean-reconstruction/1", False
        )
        self.assertIn("stage7-receipt-metrics", errors)

    def test_premature_1000_readout_is_not_stage7_evidence(self):
        forged = self.receipt(node=True)
        forged["payload"]["gate_readout"] = EXPECTED_READOUT
        forged["sha256"] = digest(forged["payload"])
        errors = _verify_stage7_receipt(
            forged, "fin-rvi-002/stage7-node-clean-reconstruction/1", True
        )
        self.assertIn("stage7-receipt-readout", errors)


if __name__ == "__main__":
    unittest.main()
