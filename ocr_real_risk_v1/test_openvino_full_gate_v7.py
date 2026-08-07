from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from ocr_real_risk_v1.core import canonical_json
from ocr_real_risk_v1.openvino_full_gate_v7 import (
    ABSTAIN_DEDUP_OR_INTEGRITY,
    ACTIVE,
    EXPECTED_PARTITION_COUNTS,
    PARTITION_COUNT,
    aggregate_partition_reports,
    build_physical_registry,
    canonical_pixel_sha256,
    claim_execution_once,
    current_code_bundle,
    exact_summary,
    execution_claim_receipt,
    new_execution_ledger,
    stable_payload,
    verify_execution_authorization,
    verify_execution_claim,
    verify_manifest_bundle,
    verify_registry_bundle,
    write_registry_bundle,
)
from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    CANDIDATE_STABLE_PAYLOAD_SHA256,
    MODEL_ARTIFACT_ID,
    MODEL_CANDIDATE_STABLE_SHA256,
    MODEL_SHA256,
    MODEL_ZIP_SHA256,
    SCIENTIFIC_MANIFEST_SHA256,
    SOURCE_COMMIT,
    SOURCE_OBJECT_SHA256,
)
from ocr_real_risk_v1.openvino_full_gate_execution_v7 import (
    MANIFEST_ARTIFACT_ID,
    MANIFEST_ARTIFACT_SHA256,
)


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def authorization_payload() -> dict:
    fields = {
        "schema": "eaat.openvino_v7_full_execution_authorization/1",
        "status": "APPROVED_FULL_EXTERNAL_GATE_ONCE",
        "authorized": True,
        "scope": ["PREPARE_REGISTRY", "EVALUATE_PARTITIONS", "AGGREGATE"],
        "candidate_stable_payload_sha256": CANDIDATE_STABLE_PAYLOAD_SHA256,
        "scientific_manifest_sha256": SCIENTIFIC_MANIFEST_SHA256,
        "source_object_sha256": SOURCE_OBJECT_SHA256,
        "run_once": True,
        "retuning_authorized": False,
        "post_outcome_retry_authorized": False,
        "execution_id": "openvino-v7-synthetic-test-execution",
        "authorization_nonce_sha256": h("authorization-nonce"),
        "manifest_artifact_id": MANIFEST_ARTIFACT_ID,
        "manifest_artifact_sha256": MANIFEST_ARTIFACT_SHA256,
        "model_artifact_id": MODEL_ARTIFACT_ID,
        "model_artifact_sha256": MODEL_ZIP_SHA256,
        "partition_count": PARTITION_COUNT,
        "runner_image": "ubuntu-24.04",
        "python_major_minor": "3.11",
        "tesseract_version": "5.3.4",
        "prior_registry_file_sha256": h("prior-registry-file"),
        "prior_registry_stable_payload_sha256": h("prior-registry-stable"),
        "execution_ledger_branch": "openvino-v7-execution-ledger-v1",
        "execution_ledger_path": "openvino-v7/execution-ledger.json",
        "code_bundle": current_code_bundle(),
    }
    seed = new_execution_ledger(fields)
    fields["execution_ledger_initial_stable_payload_sha256"] = seed[
        "stable_payload_sha256"
    ]
    return stable_payload(fields)


def write_json_file(path: Path, payload: dict) -> str:
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def claim_binding_fixture(authorization: dict) -> tuple[dict, dict]:
    ledger = new_execution_ledger(authorization)
    claimed = claim_execution_once(
        ledger,
        authorization,
        github_run_id=123456,
        github_sha="1" * 40,
        ledger_claim_commit_sha="2" * 40,
    )
    claim = execution_claim_receipt(claimed, authorization)
    binding = {
        "execution_id": authorization["execution_id"],
        "authorization_nonce_sha256": authorization[
            "authorization_nonce_sha256"
        ],
        "authorization_stable_payload_sha256": authorization[
            "stable_payload_sha256"
        ],
        "authorization_file_sha256": h("authorization-file"),
        "execution_claim_stable_payload_sha256": claim[
            "stable_payload_sha256"
        ],
        "execution_claim_file_sha256": h("claim-file"),
        "claimed_ledger_stable_payload_sha256": claim[
            "claimed_ledger_stable_payload_sha256"
        ],
        "ledger_claim_commit_sha": claim["ledger_claim_commit_sha"],
        "github_run_id": claim["github_run_id"],
        "github_sha": claim["github_sha"],
    }
    return claim, binding


def observation(
    *,
    partition: int,
    correct_baseline: bool = True,
    accepted: bool = True,
    accepted_false: bool = False,
    counterfactual: bool = False,
) -> dict:
    observation.counter += 1
    return {
        "row_index": partition * 100000 + observation.counter,
        "image_id": f"{partition:02x}{observation.counter:014x}"[-16:],
        "partition_id": partition,
        "macrofold_id": partition // 3,
        "encoded_sha256": h(f"e:{partition}:{observation.counter}"),
        "pixel_sha256": h(f"p:{partition}:{observation.counter}"),
        "truth": "1234",
        "terminal": True,
        "outcome_quarantine": {
            "detector_completed_before_annotation_query": True,
            "annotation_query_after_partition_detector_barrier": True,
        },
        "detector": {"all_calls_terminal": True},
        "baseline": {
            "eligible": True,
            "claim": "1234" if correct_baseline else "1235",
            "claim_correct": correct_baseline,
            "wall_seconds": 1.0,
        },
        "candidate": {
            "accepted": accepted,
            "final_prediction": (
                ("1235" if accepted_false else "1234") if accepted else None
            ),
            "false_accept": accepted_false,
            "verifier_wall_seconds": 0.05,
        },
        "counterfactual": {"accepted": counterfactual},
    }


observation.counter = 0


class PixelHashTests(unittest.TestCase):
    def test_pixel_hash_is_format_independent_after_rgb_decode(self):
        image = Image.new("RGB", (3, 2), (10, 20, 30))
        self.assertEqual(
            canonical_pixel_sha256(image), canonical_pixel_sha256(image.copy())
        )
        altered = image.copy()
        altered.putpixel((0, 0), (11, 20, 30))
        self.assertNotEqual(
            canonical_pixel_sha256(image), canonical_pixel_sha256(altered)
        )


class AuthorizationTests(unittest.TestCase):
    def test_authorization_fails_closed_on_wrong_scope_hash_or_code(self):
        payload = authorization_payload()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "auth.json"
            digest = write_json_file(path, payload)
            verify_execution_authorization(path, digest, "PREPARE_REGISTRY")
            with self.assertRaises(RuntimeError):
                verify_execution_authorization(path, "0" * 64, "PREPARE_REGISTRY")
            with self.assertRaises(RuntimeError):
                verify_execution_authorization(path, digest, "MERGE")
            drifted = copy.deepcopy(payload)
            drifted["code_bundle"][
                "ocr_real_risk_v1/openvino_full_gate_runner_v7.py"
            ] = "0" * 64
            drifted = stable_payload(
                {
                    key: value
                    for key, value in drifted.items()
                    if key != "stable_payload_sha256"
                }
            )
            digest = write_json_file(path, drifted)
            with self.assertRaises(RuntimeError):
                verify_execution_authorization(path, digest, "PREPARE_REGISTRY")

    def test_atomic_ledger_consumes_authorization_once(self):
        authorization = authorization_payload()
        ledger = new_execution_ledger(authorization)
        claimed = claim_execution_once(
            ledger,
            authorization,
            github_run_id=123,
            github_sha="a" * 40,
            ledger_claim_commit_sha="b" * 40,
        )
        self.assertEqual(claimed["claim_count"], 1)
        with self.assertRaises(RuntimeError):
            claim_execution_once(
                claimed,
                authorization,
                github_run_id=124,
                github_sha="c" * 40,
                ledger_claim_commit_sha="d" * 40,
            )

    def test_execution_claim_is_hash_bound_to_authorization_and_ledger(self):
        authorization = authorization_payload()
        ledger = new_execution_ledger(authorization)
        claimed = claim_execution_once(
            ledger,
            authorization,
            github_run_id=123,
            github_sha="a" * 40,
            ledger_claim_commit_sha="b" * 40,
        )
        claim = execution_claim_receipt(claimed, authorization)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "claim.json"
            digest = write_json_file(path, claim)
            verify_execution_claim(path, digest, authorization)
            with self.assertRaises(RuntimeError):
                verify_execution_claim(path, "0" * 64, authorization)
            other = copy.deepcopy(authorization)
            other["execution_id"] = "other-execution"
            other = stable_payload(
                {
                    key: value
                    for key, value in other.items()
                    if key != "stable_payload_sha256"
                }
            )
            with self.assertRaises(RuntimeError):
                verify_execution_claim(path, digest, other)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = [
            {
                "row_index": index,
                "image_id": f"{index:016x}",
                "partition": index - 1,
                "selection_rank_sha256": h(f"r{index}"),
            }
            for index in range(1, 5)
        ]
        self.images = [
            {
                **self.manifest[0],
                "encoded_sha256": h("a"),
                "pixel_sha256": h("pa"),
                "encoded_bytes": 10,
                "width": 10,
                "height": 10,
                "mode": "RGB",
            },
            {
                **self.manifest[1],
                "encoded_sha256": h("b"),
                "pixel_sha256": h("pb"),
                "encoded_bytes": 11,
                "width": 10,
                "height": 10,
                "mode": "RGB",
            },
            {
                **self.manifest[2],
                "encoded_sha256": h("c"),
                "pixel_sha256": h("pb"),
                "encoded_bytes": 12,
                "width": 10,
                "height": 10,
                "mode": "RGB",
            },
            {
                **self.manifest[3],
                "encoded_sha256": h("d"),
                "pixel_sha256": h("pd"),
                "encoded_bytes": 13,
                "width": 10,
                "height": 10,
                "mode": "RGB",
            },
        ]

    def test_registry_excludes_prior_overlap_and_internal_pixel_duplicate(self):
        prior = {"complete": True, "encoded_sha256": [h("d")], "pixel_sha256": []}
        result = build_physical_registry(
            self.manifest, self.images, prior, minimum_active=1
        )
        rows = {row["row_index"]: row for row in result["records"]}
        self.assertEqual(rows[1]["disposition"], ACTIVE)
        self.assertEqual(rows[2]["disposition"], ACTIVE)
        self.assertEqual(rows[3]["disposition"], "EXCLUDED_INTERNAL_DUPLICATE")
        self.assertEqual(rows[4]["disposition"], "EXCLUDED_PRIOR_OVERLAP")
        self.assertEqual(result["active_count"], 2)

    def test_registry_fails_closed_on_missing_or_extra_rows(self):
        prior = {"complete": True, "encoded_sha256": [], "pixel_sha256": []}
        with self.assertRaises(RuntimeError):
            build_physical_registry(
                self.manifest, self.images[:-1], prior, minimum_active=1
            )
        extra = self.images + [
            {
                **self.images[0],
                "row_index": 99,
                "image_id": "0000000000000099",
            }
        ]
        with self.assertRaises(RuntimeError):
            build_physical_registry(self.manifest, extra, prior, minimum_active=1)

    def test_registry_bundle_round_trip_is_hash_bound(self):
        prior = {"complete": True, "encoded_sha256": [], "pixel_sha256": []}
        registry = build_physical_registry(
            self.manifest, self.images, prior, minimum_active=1
        )
        authorization = authorization_payload()
        _, binding = claim_binding_fixture(authorization)
        registry = stable_payload(
            {
                **{
                    key: value
                    for key, value in registry.items()
                    if key != "stable_payload_sha256"
                },
                "authorization_binding": binding,
                "code_bundle": current_code_bundle(),
            }
        )
        with tempfile.TemporaryDirectory() as td:
            receipt = write_registry_bundle(registry, Path(td))
            summary = verify_registry_bundle(Path(td))
            self.assertEqual(summary["active_count"], 3)
            self.assertEqual(
                summary["stable_payload_sha256"], receipt["stable_payload_sha256"]
            )
            records = Path(td) / "registry_records.jsonl"
            records.write_text(records.read_text() + "{}\n")
            with self.assertRaises(RuntimeError):
                verify_registry_bundle(Path(td))

    def test_registry_underpower_is_terminal_abstention(self):
        prior = {
            "complete": True,
            "encoded_sha256": [h("a"), h("b"), h("c"), h("d")],
            "pixel_sha256": [],
        }
        result = build_physical_registry(
            self.manifest, self.images, prior, minimum_active=1
        )
        self.assertEqual(result["status"], ABSTAIN_DEDUP_OR_INTEGRITY)
        self.assertFalse(result["evaluation_authorized"])


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.authorization = authorization_payload()
        _, self.binding = claim_binding_fixture(self.authorization)
        self.bundle = current_code_bundle()

    def report(self, partition: int, rows: list[dict]) -> dict:
        return stable_payload(
            {
                "schema": "eaat.openvino_v7_partition_report/1",
                "partition_id": partition,
                "partition_count": PARTITION_COUNT,
                "record_count": len(rows),
                "candidate_stable_payload_sha256": CANDIDATE_STABLE_PAYLOAD_SHA256,
                "registry_stable_payload_sha256": h("registry"),
                "scientific_manifest_sha256": SCIENTIFIC_MANIFEST_SHA256,
                "authorization_binding": self.binding,
                "code_bundle": self.bundle,
                "source_identity": {
                    "source_commit": SOURCE_COMMIT,
                    "all_match_frozen_commit": True,
                },
                "runtime": {"strict_match": True},
                "model": {
                    "artifact_id": MODEL_ARTIFACT_ID,
                    "artifact_zip_sha256": MODEL_ZIP_SHA256,
                    "model_sha256": MODEL_SHA256,
                    "candidate_stable_payload_sha256": MODEL_CANDIDATE_STABLE_SHA256,
                    "tree_count": 500,
                },
                "executor_source_sha256": self.bundle[
                    "ocr_real_risk_v1/openvino_full_gate_runner_v7.py"
                ],
                "detector_barrier_sha256": h(f"barrier:{partition}"),
                "detector_barrier_rows": len(rows),
                "annotation_query_executed_after_detector_barrier": True,
                "execution_complete": True,
                "observations": rows,
            }
        )

    def make_reports(self, per_partition: int = 100) -> list[dict]:
        reports = []
        for partition in range(PARTITION_COUNT):
            rows = [
                observation(
                    partition=partition,
                    correct_baseline=(index % 4 != 0),
                    accepted=(index < per_partition // 2),
                    accepted_false=False,
                    counterfactual=False,
                )
                for index in range(per_partition)
            ]
            reports.append(self.report(partition, rows))
        return reports

    def aggregate(self, reports: list[dict], count: int) -> dict:
        return aggregate_partition_reports(
            reports,
            expected_partition_counts=[count] * 12,
            registry_stable_payload_sha256=h("registry"),
            expected_code_bundle=self.bundle,
            authorization_binding=self.binding,
            minimum_active=1,
        )

    def test_exact_summary_rejects_counterfactual_or_low_coverage(self):
        rows = [
            observation(
                partition=index % 12,
                correct_baseline=(index % 10 != 0),
                accepted=(index < 50),
                counterfactual=(index == 0),
            )
            for index in range(1000)
        ]
        summary = exact_summary(rows, minimum_selected=1)
        self.assertFalse(summary["pass"])
        self.assertLess(summary["coverage_lower"], 0.25)

    def test_aggregate_passes_complete_clean_reports_and_leave_one_out(self):
        result = self.aggregate(self.make_reports(500), 500)
        self.assertEqual(result["status"], "PASS_FULL_EXTERNAL_GATE")
        self.assertEqual(result["stability"]["semantics"], "leave_one_macrofold_out")
        self.assertEqual(result["stability"]["passes"], 4)
        self.assertFalse(result["speed"]["claim_authorized"])

    def test_aggregate_rejects_missing_duplicate_or_nonterminal_partition(self):
        reports = self.make_reports(20)
        with self.assertRaises(RuntimeError):
            self.aggregate(reports[:-1], 20)
        with self.assertRaises(RuntimeError):
            self.aggregate(reports + [copy.deepcopy(reports[0])], 20)
        bad = copy.deepcopy(reports)
        bad[0]["execution_complete"] = False
        bad[0] = stable_payload(
            {key: value for key, value in bad[0].items() if key != "stable_payload_sha256"}
        )
        with self.assertRaises(RuntimeError):
            self.aggregate(bad, 20)

    def test_aggregate_abstains_on_duplicate_hash_or_quarantine_violation(self):
        reports = self.make_reports(20)
        reports[1]["observations"][0]["pixel_sha256"] = reports[0]["observations"][0][
            "pixel_sha256"
        ]
        reports[1] = self.report(1, reports[1]["observations"])
        self.assertEqual(
            self.aggregate(reports, 20)["status"], ABSTAIN_DEDUP_OR_INTEGRITY
        )
        reports = self.make_reports(20)
        reports[0]["observations"][0]["outcome_quarantine"][
            "detector_completed_before_annotation_query"
        ] = False
        reports[0] = self.report(0, reports[0]["observations"])
        self.assertEqual(
            self.aggregate(reports, 20)["status"], ABSTAIN_DEDUP_OR_INTEGRITY
        )

    def test_aggregate_rejects_runtime_model_code_or_barrier_identity_drift(self):
        for field, mutation in (
            ("runtime", {"strict_match": False}),
            ("model", {"artifact_id": -1}),
            ("code_bundle", {"bad": "0" * 64}),
        ):
            reports = self.make_reports(20)
            reports[0][field] = mutation
            reports[0] = stable_payload(
                {
                    key: value
                    for key, value in reports[0].items()
                    if key != "stable_payload_sha256"
                }
            )
            with self.assertRaises(RuntimeError):
                self.aggregate(reports, 20)
        reports = self.make_reports(20)
        reports[0]["detector_barrier_rows"] = 19
        reports[0] = stable_payload(
            {key: value for key, value in reports[0].items() if key != "stable_payload_sha256"}
        )
        with self.assertRaises(RuntimeError):
            self.aggregate(reports, 20)


class RuntimeStructureTests(unittest.TestCase):
    def test_partition_executor_streams_bytes_and_persists_barrier_first(self):
        from ocr_real_risk_v1 import openvino_full_gate_runner_v7 as module

        image_source = inspect.getsource(module._fetch_partition_images)
        annotation_source = inspect.getsource(module._iter_partition_annotations)
        self.assertIn("fetchmany", image_source)
        self.assertNotIn("fetchall", image_source)
        self.assertIn("fetchmany", annotation_source)
        self.assertNotIn("fetchall", annotation_source)
        source = inspect.getsource(module.evaluate_partition_from_source)
        detector = source.index("_run_outcome_blind_detector")
        barrier_write = source.index("_write_jsonl(barrier_path")
        annotations = source.index("_iter_partition_annotations")
        scoring = source.index("_score_partition_after_barrier")
        self.assertLess(detector, barrier_write)
        self.assertLess(barrier_write, annotations)
        self.assertLess(barrier_write, scoring)

    def test_registry_prepare_projection_excludes_annotations(self):
        from ocr_real_risk_v1 import openvino_full_gate_prepare_v7 as module

        source = inspect.getsource(module.prepare_registry_from_source)
        projection = source.split("cursor = connection.execute(", 1)[1].split(")\n", 1)[0]
        self.assertNotIn("texts", projection)
        self.assertNotIn("bboxes", projection)
        self.assertNotIn("polygons", projection)


class ManifestBundleTests(unittest.TestCase):
    def test_real_terminal_manifest_bundle_replays(self):
        path = Path(
            os.environ.get(
                "OPENVINO_MANIFEST_ROOT", "/mnt/data/openvino_manifest_artifact"
            )
        )
        if not path.exists():
            self.skipTest("terminal manifest artifact not mounted")
        summary = verify_manifest_bundle(path)
        self.assertEqual(summary["scientific_count"], 20613)
        self.assertEqual(summary["partition_counts"], EXPECTED_PARTITION_COUNTS)
        self.assertFalse(summary["full_gate_authorized"])


if __name__ == "__main__":
    unittest.main()
