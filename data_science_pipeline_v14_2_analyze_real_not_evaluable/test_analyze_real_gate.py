from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import analyze_real_gate as a


HERE = Path(__file__).resolve().parent
BASE = json.loads((HERE / "ANALYZE_REAL_GATE_CONTRACT.json").read_text())


def contract_record(event_id: str = "contract-1", method: str | None = "open", outcome=None):
    return {
        "event_id": event_id,
        "event_role": "CONTRACT",
        "amount_role": "CONTRACT_VALUE",
        "date_role": "CONTRACT_DATE",
        "procurement_method": method,
        "low_competition": outcome,
        "currency": "HNL",
        "amount_hnl": "100.00",
        "buyer_id": "PRIVATE-BUYER",
        "supplier_id": "PRIVATE-SUPPLIER",
    }


def payment_record():
    return {
        "event_id": "payment-1",
        "event_role": "PAYMENT",
        "amount_role": "PAYMENT_VALUE",
        "date_role": "PAYMENT_DATE",
        "procurement_method": None,
        "low_competition": None,
        "currency": "HNL",
        "amount_hnl": "100.00",
    }


def execute(records):
    snapshot = {"schema": "data-science-pipeline/semantic-snapshot/2", "records": records}
    raw = a.canonical_bytes(snapshot)
    contract = copy.deepcopy(BASE)
    contract["input"]["snapshot_sha256"] = a.sha256_bytes(raw)
    contract["input"]["expected_rows"] = len(records)
    return a.analyse(snapshot, contract, input_sha256=a.sha256_bytes(raw))


class AnalyzeRealGateTests(unittest.TestCase):
    def baseline(self):
        return execute([contract_record(), payment_record()])

    def test_01_canonical_bytes_end_newline(self):
        self.assertTrue(a.canonical_bytes({"b": 1, "a": 2}).endswith(b"\n"))

    def test_02_semantic_records_two(self):
        self.assertEqual(len(a.semantic_records({"records": [contract_record(), payment_record()]})), 2)

    def test_03_row_order_invariant(self):
        left = self.baseline()
        right = execute([payment_record(), contract_record()])
        self.assertEqual(a.canonical_bytes(left), a.canonical_bytes(right))

    def test_04_payment_excluded(self):
        self.assertEqual(self.baseline()["population"]["excluded_role_counts"], {"PAYMENT": 1})

    def test_05_one_eligible_contract(self):
        self.assertEqual(self.baseline()["population"]["eligible_contract_rows"], 1)

    def test_06_terminal_state(self):
        self.assertEqual(self.baseline()["terminal_state"], "ANALYSIS_NOT_EVALUABLE")

    def test_07_reason_code(self):
        self.assertEqual(self.baseline()["reason_code"], "NOT_EVALUABLE_MIN_CELL_SIZE")

    def test_08_registered_analysis_not_executed(self):
        self.assertIs(self.baseline()["registered_analysis"]["executed"], False)

    def test_09_minimum_evaluable_cell_zero(self):
        self.assertEqual(self.baseline()["population"]["minimum_observed_evaluable_cell_n"], 0)

    def test_10_cross_role_aggregation_false(self):
        self.assertIs(self.baseline()["guardrails"]["cross_role_amount_aggregation_performed"], False)

    def test_11_low_competition_not_imputed(self):
        self.assertIs(self.baseline()["guardrails"]["low_competition_imputed"], False)

    def test_12_raw_identity_not_exported(self):
        self.assertIs(self.baseline()["guardrails"]["raw_identity_exported"], False)

    def test_13_no_ranking(self):
        self.assertIs(self.baseline()["guardrails"]["ranking_emitted"], False)

    def test_14_no_causal_claim(self):
        self.assertIs(self.baseline()["guardrails"]["causal_claim_emitted"], False)

    def test_15_no_wrongdoing_label(self):
        self.assertIs(self.baseline()["guardrails"]["wrongdoing_label_emitted"], False)

    def test_16_stage10_input_false(self):
        self.assertIs(self.baseline()["readiness"]["stage10_canary_input_ready"], False)

    def test_17_stage10_global_false(self):
        self.assertIs(self.baseline()["readiness"]["stage10_global_unblocked"], False)

    def test_18_next_gate_scale_up(self):
        self.assertIn("at_least_five", self.baseline()["readiness"]["next_gate"])

    def test_19_hash_mismatch_fails(self):
        snapshot = {"records": [contract_record(), payment_record()]}
        with self.assertRaisesRegex(a.GateError, "SHA256_MISMATCH"):
            a.analyse(snapshot, copy.deepcopy(BASE), input_sha256="0" * 64)

    def test_20_row_count_mismatch_fails(self):
        snapshot = {"records": [contract_record()]}
        raw = a.canonical_bytes(snapshot)
        contract = copy.deepcopy(BASE)
        contract["input"]["snapshot_sha256"] = a.sha256_bytes(raw)
        contract["input"]["expected_rows"] = 2
        with self.assertRaisesRegex(a.GateError, "ROW_COUNT_MISMATCH"):
            a.analyse(snapshot, contract, input_sha256=a.sha256_bytes(raw))

    def test_21_no_records_fails(self):
        with self.assertRaisesRegex(a.GateError, "NO_SEMANTIC_EVENT_RECORDS"):
            a.semantic_records({"records": []})

    def test_22_duplicate_event_id_fails(self):
        second = contract_record("contract-1", "direct", False)
        with self.assertRaisesRegex(a.GateError, "DUPLICATE_SEMANTIC_EVENT_ID"):
            a.semantic_records({"records": [contract_record(), second]})

    def test_23_precondition_met_fails_closed(self):
        rows = [contract_record(f"d-{i}", "direct", bool(i % 2)) for i in range(5)]
        rows += [contract_record(f"o-{i}", "open", bool(i % 2)) for i in range(5)]
        with self.assertRaisesRegex(a.GateError, "PRECONDITION_UNEXPECTEDLY_MET"):
            execute(rows)

    def test_24_unsupported_method_reported(self):
        result = execute([contract_record(method="selective"), payment_record()])
        self.assertEqual(result["population"]["unsupported_method_rows"], 1)

    def test_25_boolean_outcome_counted(self):
        result = execute([contract_record(outcome=False), payment_record()])
        self.assertEqual(result["population"]["group_evaluable_outcome_counts"]["OPEN"], 1)

    def test_26_missing_outcome_counted(self):
        self.assertEqual(self.baseline()["population"]["missing_outcome_rows"], 1)

    def test_27_private_values_absent_from_result(self):
        text = a.canonical_bytes(self.baseline()).decode()
        self.assertNotIn("PRIVATE-BUYER", text)
        self.assertNotIn("PRIVATE-SUPPLIER", text)

    def test_28_deterministic_result(self):
        self.assertEqual(a.sha256_value(self.baseline()), a.sha256_value(self.baseline()))

    def test_29_payment_guard_true(self):
        self.assertIs(self.baseline()["guardrails"]["payment_excluded_from_contract_population"], True)

    def test_30_governance_preserved(self):
        governance = self.baseline()["governance"]
        self.assertEqual(governance["external_cost_usd"], 0.0)
        self.assertIs(governance["production_modified"], False)
        self.assertIs(governance["stage10_unblocked"], False)


def _make_null_output_test(field):
    def test(self):
        self.assertIsNone(self.baseline()["statistical_outputs"][field])
    return test


for _index, _field in enumerate(
    ["p_value", "risk_difference", "confidence_interval", "q_value", "negative_control_p_value", "outlier_candidates"],
    start=31,
):
    setattr(AnalyzeRealGateTests, f"test_{_index:02d}_{_field}_null", _make_null_output_test(_field))


if __name__ == "__main__":
    unittest.main(verbosity=2)
