from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from fin_rvi_002_stage2.build_frozen_corpus_v2 import build_corpus
from fin_rvi_002_stage2.evidence_ladder import (
    FORBIDDEN_POLICY_FIELDS,
    POLICY_FIELDS,
    evidence_ladder,
    policy_view,
)
from fin_rvi_002_stage2.run_stage2_v2 import (
    POLICIES,
    build_report,
    evaluate_policies,
    rotate_sefin_evidence,
    sha256_payload,
)


class EvidenceLadderV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = Path("reports/fin_rvi_002_stage1")
        cls.corpus = build_corpus(
            Path("fin_rvi_002_stage2/frozen_pair_manifest_v2.json"),
            cls.source / "known_target_hits.json",
        )
        cls.rows = cls.corpus["rows"]
        cls.source_report = json.loads((cls.source / "report.json").read_text())
        cls.holdout = [
            json.loads(line)
            for line in (cls.source / "holdout_decisions.jsonl").read_text().splitlines()
            if line
        ]

    def row_for(self, rule: str, sefin_ocid: str | None = None):
        return next(
            row
            for row in self.rows
            if row["gold_rule"] == rule
            and (sefin_ocid is None or row["sefin_ocid"] == sefin_ocid)
        )

    def test_gold_fields_are_inaccessible_to_policy(self) -> None:
        self.assertFalse(FORBIDDEN_POLICY_FIELDS & set(POLICY_FIELDS))
        row = self.rows[0]
        visible = policy_view(row)
        self.assertFalse(FORBIDDEN_POLICY_FIELDS & set(visible))

    def test_contract_advance_and_estimate_promote(self) -> None:
        for row in self.rows:
            if row["gold_rule"] == "FHIS_108877_CONTRACTOR_PAYMENT":
                self.assertTrue(evidence_ladder(row)["promote"])

    def test_auxiliary_and_publication_do_not_promote(self) -> None:
        rules = {"FHIS_108877_ANCILLARY", "SIT_GA_001_PUBLICATION"}
        for row in self.rows:
            if row["gold_rule"] in rules:
                self.assertFalse(evidence_ladder(row)["promote"])

    def test_temporal_source_semantics_fail_closed(self) -> None:
        for row in self.rows:
            if row["gold_rule"] == "SIT_CO_496_TEMPORAL_CONFLICT":
                decision = evidence_ladder(row)
                self.assertFalse(decision["promote"])
                self.assertTrue(
                    any(blocker.startswith("TEMPORAL_") for blocker in decision["blockers"])
                )

    def test_consortium_authority_fails_closed(self) -> None:
        for row in self.rows:
            if row["gold_rule"] == "SIT_SU_038_CONSORTIUM_MEMBER":
                decision = evidence_ladder(row)
                self.assertFalse(decision["promote"])
                self.assertIn(
                    "PAYEE_AUTHORITY_UNKNOWN_CONSORTIUM_AUTHORITY", decision["blockers"]
                )

    def test_sealed_test_dominates_code_supplier_baseline(self) -> None:
        metrics = evaluate_policies(self.rows, "SEALED_TEST")
        strong = metrics["B1_CODE_SUPPLIER"]
        ladder = metrics["EVIDENCE_LADDER"]
        self.assertGreater(strong["unsafe_overpromotions"], 0)
        self.assertEqual(ladder["unsafe_overpromotions"], 0)
        self.assertEqual(ladder["supported_recovered"], ladder["positive_expected"])
        self.assertGreater(ladder["binary_correct"], strong["binary_correct"])

    def test_negative_control_is_worse(self) -> None:
        original = evaluate_policies(self.rows, "SEALED_TEST")["EVIDENCE_LADDER"]
        rotated = evaluate_policies(
            rotate_sefin_evidence(copy.deepcopy(self.rows)), "SEALED_TEST"
        )["EVIDENCE_LADDER"]
        self.assertTrue(
            rotated["unsafe_overpromotions"] > original["unsafe_overpromotions"]
            or rotated["binary_correct"] < original["binary_correct"]
        )

    def test_report_is_deterministic_and_candidate_passes(self) -> None:
        first = build_report(self.corpus, self.source_report, self.holdout)
        second = build_report(self.corpus, self.source_report, self.holdout)
        self.assertEqual(first, second)
        self.assertEqual(first["sha256"], sha256_payload(first["payload"]))
        self.assertEqual(first["payload"]["selected_policy"], "EVIDENCE_LADDER")
        self.assertEqual(
            first["payload"]["gate_readout"]["G07"],
            "PASS_CANDIDATE_PENDING_PUBLIC_CLEAN_REPLAY",
        )
        self.assertTrue(all(first["payload"]["gate_checks"].values()))
        self.assertEqual(set(first["payload"]["policy_metrics_all"]), set(POLICIES))

    def test_payload_tamper_is_detected(self) -> None:
        report = build_report(self.corpus, self.source_report, self.holdout)
        altered = copy.deepcopy(report)
        altered["payload"]["gate_readout"]["G09"] = "FORGED_PASS"
        self.assertNotEqual(altered["sha256"], sha256_payload(altered["payload"]))


if __name__ == "__main__":
    unittest.main()
