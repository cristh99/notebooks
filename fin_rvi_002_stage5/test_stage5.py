from __future__ import annotations

import json
import unittest
from pathlib import Path

from fin_rvi_002_stage5.verify_clean_replay import verify


class CleanReplayVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = (
            Path("/tmp/stage4-art")
            if Path("/tmp/stage4-art").exists()
            else Path("reports/fin_rvi_002_stage5/stage4")
        )

    def test_reference_artifact_passes_when_available(self) -> None:
        if not (self.root / "report.json").exists():
            self.skipTest("reference artifact not mounted")
        receipt = verify(
            self.root / "report.json",
            self.root / "stage4_compact_rows.jsonl",
            self.root / "stage4_confirmed_labels.jsonl",
        )
        self.assertTrue(all(receipt["payload"]["gates"].values()))
        self.assertEqual(receipt["payload"]["gate_readout"]["finance_score"], 920)

    def test_tampered_rows_fail_when_available(self) -> None:
        if not (self.root / "report.json").exists():
            self.skipTest("reference artifact not mounted")
        rows = (self.root / "stage4_compact_rows.jsonl").read_text().splitlines()
        first = json.loads(rows[0])
        first["policy_decision"] = (
            "SUPPORTED"
            if first["policy_decision"] != "SUPPORTED"
            else "REJECTED"
        )
        rows[0] = json.dumps(first, sort_keys=True)
        tampered = Path("/tmp/tampered-stage5-rows.jsonl")
        tampered.write_text("\n".join(rows) + "\n")
        receipt = verify(
            self.root / "report.json",
            tampered,
            self.root / "stage4_confirmed_labels.jsonl",
        )
        self.assertFalse(all(receipt["payload"]["gates"].values()))


if __name__ == "__main__":
    unittest.main()
