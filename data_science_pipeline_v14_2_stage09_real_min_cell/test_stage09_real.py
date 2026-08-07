from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import stage09_real as s


HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "ANALYSIS_CONTRACT_V14_1.json"
SNAPSHOT_PATH = HERE / "REAL_SEMANTIC_SNAPSHOT.json"
BINDING_PATH = HERE / "COMPATIBILITY_BINDING.json"
RESULT_PATH = HERE / "LOCAL_RESULT.json"


def canonical(value):
    return s.canonical_bytes(value)


class Stage09RealCanaryTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.contract = json.loads(CONTRACT_PATH.read_text())
        self.snapshot = json.loads(SNAPSHOT_PATH.read_text())
        self.binding = json.loads(BINDING_PATH.read_text())
        self.result = json.loads(RESULT_PATH.read_text())

    def build(self, contract=None, snapshot=None, binding=None):
        return s.build_result(
            copy.deepcopy(contract if contract is not None else self.contract),
            copy.deepcopy(snapshot if snapshot is not None else self.snapshot),
            copy.deepcopy(binding if binding is not None else self.binding),
        )

    def test_001_exact_contract_sha(self):
        self.assertEqual(s.sha256_file(CONTRACT_PATH), s.ANALYSIS_CONTRACT_SHA256)

    def test_002_exact_snapshot_sha(self):
        self.assertEqual(s.sha256_file(SNAPSHOT_PATH), s.SEMANTIC_SNAPSHOT_SHA256)

    def test_003_contract_is_canonical(self):
        self.assertEqual(CONTRACT_PATH.read_bytes(), canonical(self.contract))

    def test_004_snapshot_is_canonical(self):
        self.assertEqual(SNAPSHOT_PATH.read_bytes(), canonical(self.snapshot))

    def test_005_binding_is_canonical(self):
        self.assertEqual(BINDING_PATH.read_bytes(), canonical(self.binding))

    def test_006_result_is_canonical(self):
        self.assertEqual(RESULT_PATH.read_bytes(), canonical(self.result))

    def test_007_contract_validation_passes(self):
        s.validate_contract(self.contract)

    def test_008_binding_validation_passes(self):
        self.assertEqual(s.load_binding(BINDING_PATH)["scope"], "EXACT_PR149_SNAPSHOT_ONLY")

    def test_009_snapshot_validation_passes(self):
        s.validate_snapshot(self.snapshot, self.contract, self.binding)

    def test_010_terminal_is_not_evaluable(self):
        self.assertEqual(self.result["terminal_state"], "ANALYSIS_NOT_EVALUABLE")

    def test_011_terminal_detail_is_minimum_cell(self):
        self.assertEqual(self.result["terminal_detail"], "ANALYSIS_NOT_EVALUABLE_MINIMUM_CELL_SIZE")

    def test_012_exact_input_count(self):
        self.assertEqual(self.result["population"]["input_semantic_records"], 2)

    def test_013_exact_contract_population_count(self):
        self.assertEqual(self.result["population"]["eligible_contract_records"], 1)

    def test_014_payment_is_excluded(self):
        self.assertEqual(self.result["population"]["excluded_event_roles"], ["PAYMENT"])

    def test_015_no_cross_role_aggregation(self):
        self.assertFalse(self.result["population"]["cross_role_amount_aggregation_performed"])

    def test_016_open_group_count(self):
        self.assertEqual(self.result["population"]["group_counts"]["OPEN"], 1)

    def test_017_direct_group_absent(self):
        self.assertEqual(self.result["population"]["group_counts"]["DIRECT"], 0)

    def test_018_open_outcome_is_missing(self):
        self.assertEqual(self.result["population"]["missing_outcome_counts"]["OPEN"], 1)

    def test_019_no_observed_outcomes(self):
        self.assertEqual(sum(self.result["population"]["observed_outcome_counts"].values()), 0)

    def test_020_all_contingency_cells_zero(self):
        cells = self.result["population"]["contingency_cells"]
        self.assertEqual(sum(v for group in cells.values() for v in group.values()), 0)

    def test_021_minimum_cell_threshold_frozen(self):
        self.assertEqual(self.result["preregistration"]["minimum_cell_n"], 5)

    def test_022_minimum_cell_gate_closed(self):
        self.assertFalse(self.result["gates"]["minimum_cell_gate"])

    def test_023_complete_outcome_gate_closed(self):
        self.assertFalse(self.result["gates"]["complete_outcome_gate"])

    def test_024_both_groups_gate_closed(self):
        self.assertFalse(self.result["gates"]["both_preregistered_groups_present"])

    def test_025_inferential_execution_forbidden(self):
        self.assertFalse(self.result["gates"]["inferential_execution_allowed"])

    def test_026_no_inferential_outputs(self):
        self.assertEqual(self.result["hypothesis_results"][0]["inferential_outputs_emitted"], 0)

    def test_027_hypothesis_not_evaluated(self):
        self.assertEqual(self.result["hypothesis_results"][0]["status"], "NOT_EVALUATED")

    def test_028_all_fail_closed_reasons_present(self):
        self.assertEqual(
            set(self.result["hypothesis_results"][0]["reasons"]),
            {
                "MINIMUM_CELL_SIZE_NOT_MET",
                "OUTCOME_NOT_REPORTED_IN_SOURCE",
                "PREREGISTERED_GROUP_MISSING",
            },
        )

    def test_029_negative_control_not_run(self):
        self.assertEqual(self.result["negative_control"]["status"], "NOT_RUN_INFERENTIAL_GATE_CLOSED")

    def test_030_negative_control_not_promoted(self):
        self.assertFalse(self.result["negative_control"]["promoted"])

    def test_031_multiplicity_not_applied(self):
        self.assertEqual(self.result["multiplicity"]["eligible_hypotheses"], 0)

    def test_032_amount_diagnostics_not_run(self):
        self.assertEqual(self.result["amount_diagnostics"]["review_candidates_emitted"], 0)

    def test_033_no_forbidden_keys(self):
        self.assertFalse(s.contains_forbidden_key(self.result))

    def test_034_no_claims_emitted(self):
        self.assertEqual(sum(self.result["claim_boundary"].values()), 0)

    def test_035_stage10_stays_blocked(self):
        self.assertFalse(self.result["governance"]["stage10_global_unblocked"])

    def test_036_stage10_canary_not_ready(self):
        self.assertFalse(self.result["governance"]["stage10_canary_input_ready"])

    def test_037_zero_external_cost(self):
        self.assertEqual(self.result["governance"]["external_cost_usd"], 0.0)

    def test_038_zero_production_modification(self):
        self.assertFalse(self.result["governance"]["production_modified"])

    def test_039_zero_merge_authorization(self):
        self.assertFalse(self.result["governance"]["merge_authorized"])

    def test_040_input_conservation(self):
        self.assertTrue(self.result["population"]["input_conservation_observed"])

    def test_041_exact_excluded_commitment_only(self):
        excluded = self.result["excluded_records"]
        self.assertEqual(excluded["count"], 1)
        self.assertEqual(excluded["raw_records_emitted"], 0)
        self.assertEqual(excluded["commitments"], ["8f30789114b01b951d4c73c0ae90ed2d35572c7a0ab8593d7a626f5edfe7986f"])

    def test_042_case_only_open_mapping(self):
        self.assertEqual(s.canonical_method("open"), "OPEN")
        self.assertEqual(s.canonical_method("OPEN"), "OPEN")

    def test_043_direct_mapping(self):
        self.assertEqual(s.canonical_method("direct"), "DIRECT")
        self.assertEqual(s.canonical_method("DIRECT"), "DIRECT")

    def test_044_unknown_method_not_mapped(self):
        self.assertIsNone(s.canonical_method("limited"))

    def test_045_row_order_invariance(self):
        reversed_snapshot = copy.deepcopy(self.snapshot)
        reversed_snapshot["records"] = list(reversed(reversed_snapshot["records"]))
        self.assertEqual(self.build(), self.build(snapshot=reversed_snapshot))

    def test_046_byte_identical_replay(self):
        first = canonical(self.build())
        second = canonical(self.build())
        self.assertEqual(first, second)

    def test_047_result_self_hash(self):
        without = dict(self.result)
        observed = without.pop("result_sha256")
        self.assertEqual(observed, hashlib.sha256(canonical(without)).hexdigest())

    def test_048_execute_reproduces_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            s.execute(CONTRACT_PATH, SNAPSHOT_PATH, BINDING_PATH, output)
            self.assertEqual(output.read_bytes(), RESULT_PATH.read_bytes())

    def test_049_payment_amount_does_not_enter_population(self):
        eligible, excluded = s.filter_population(self.snapshot["records"], self.contract)
        self.assertEqual([row["amount_hnl"] for row in eligible], [81627.0])
        self.assertEqual(len(excluded), 1)

    def test_050_exact_real_data_evaluation_count(self):
        self.assertEqual(self.result["governance"]["external_real_data_evaluations"], 1)


def _install_mutation_test(name, target, path, value, expected_exception):
    def test(self):
        obj = copy.deepcopy(getattr(self, target))
        cursor = obj
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value
        if target == "contract":
            with self.assertRaises(expected_exception):
                s.validate_contract(obj)
        elif target == "snapshot":
            with self.assertRaises(expected_exception):
                s.validate_snapshot(obj, self.contract, self.binding)
        else:
            with tempfile.TemporaryDirectory() as directory:
                candidate = Path(directory) / "binding.json"
                candidate.write_bytes(canonical(obj))
                with self.assertRaises(expected_exception):
                    s.load_binding(candidate)
    setattr(Stage09RealCanaryTests, name, test)


# Ten additional fail-closed mutation tests: total 60.
_MUTATIONS = [
    ("test_051_contract_minimum_cell_tamper_fails", "contract", ["statistics", "minimum_cell_n"], 1, s.ContractError),
    ("test_052_contract_hypothesis_tamper_fails", "contract", ["hypotheses", 0, "id"], "H09-X", s.ContractError),
    ("test_053_contract_group_tamper_fails", "contract", ["hypotheses", 0, "groups"], ["OPEN", "DIRECT"], s.ContractError),
    ("test_054_contract_cost_tamper_fails", "contract", ["governance", "external_cost_usd"], 1.0, s.ContractError),
    ("test_055_snapshot_terminal_tamper_fails", "snapshot", ["terminal_state"], "SEMANTIC_QUARANTINED", s.SnapshotError),
    ("test_056_snapshot_quarantine_tamper_fails", "snapshot", ["quarantine"], [{"reason": "X"}], s.SnapshotError),
    ("test_057_snapshot_relationship_claim_tamper_fails", "snapshot", ["claim_boundary", "cross_source_relationship_assertions"], 1, s.SnapshotError),
    ("test_058_binding_scope_tamper_fails", "binding", ["scope"], "ANY_SNAPSHOT", s.BindingError),
    ("test_059_binding_threshold_tamper_fails", "binding", ["threshold_changed"], True, s.BindingError),
    ("test_060_binding_mapping_tamper_fails", "binding", ["method_mapping"], {"open": "DIRECT"}, s.BindingError),
]
for mutation in _MUTATIONS:
    _install_mutation_test(*mutation)


if __name__ == "__main__":
    unittest.main()
