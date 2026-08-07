from __future__ import annotations

import inspect
import unittest


class PreexecutionEntrypointTests(unittest.TestCase):
    def test_all_source_entrypoints_gate_runtime_before_data_access(self):
        from ocr_real_risk_v1 import openvino_full_gate_aggregate_v7 as aggregate
        from ocr_real_risk_v1 import openvino_full_gate_prepare_v7 as prepare
        from ocr_real_risk_v1 import openvino_full_gate_runner_v7 as runner

        prepare_source = inspect.getsource(prepare.prepare_registry_from_source)
        self.assertLess(
            prepare_source.index("verify_preexecution_gate"),
            prepare_source.index("verify_manifest_bundle"),
        )
        self.assertLess(
            prepare_source.index("verify_preexecution_gate"),
            prepare_source.index("_duckdb_connection"),
        )
        self.assertIn('"preexecution_binding": preexecution', prepare_source)

        runner_source = inspect.getsource(runner.evaluate_partition_from_source)
        self.assertLess(
            runner_source.index("verify_preexecution_gate"),
            runner_source.index("verify_manifest_bundle"),
        )
        self.assertLess(
            runner_source.index("verify_preexecution_gate"),
            runner_source.index("_fetch_partition_images"),
        )
        self.assertIn('"preexecution_binding": preexecution', runner_source)

        aggregate_source = inspect.getsource(aggregate.aggregate_from_files)
        self.assertLess(
            aggregate_source.index("verify_preexecution_gate"),
            aggregate_source.index("verify_registry_bundle"),
        )
        self.assertIn(
            'registry_receipt.get("preexecution_binding") != preexecution',
            aggregate_source,
        )
        self.assertIn("expected_preexecution=preexecution", aggregate_source)


if __name__ == "__main__":
    unittest.main()
