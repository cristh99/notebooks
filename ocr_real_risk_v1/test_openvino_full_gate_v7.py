from __future__ import annotations

import copy
import hashlib
import inspect
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
    exact_summary,
    stable_payload,
    verify_execution_authorization,
    verify_manifest_bundle,
    verify_registry_bundle,
    write_registry_bundle,
)


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def observation(
    *,
    partition: int,
    correct_baseline: bool = True,
    accepted: bool = True,
    accepted_false: bool = False,
    counterfactual: bool = False,
) -> dict:
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
    def test_authorization_fails_closed_on_wrong_scope_or_hash(self):
        payload = stable_payload(
            {
                "schema": "eaat.openvino_v7_full_execution_authorization/1",
                "status": "APPROVED_FULL_EXTERNAL_GATE_ONCE",
                "authorized": True,
                "scope": [
                    "PREPARE_REGISTRY",
                    "EVALUATE_PARTITIONS",
                    "AGGREGATE",
                ],
                "candidate_stable_payload_sha256": (
                    "160a3e79c6075a6741a1a6365b0c833115bfc6e156176cb4cb5744b1189119cd"
                ),
                "scientific_manifest_sha256": (
                    "3340183dca08229e3cd1d17472043316867381d8b4f70e6f2d74e3592cd89d4c"
                ),
                "source_object_sha256": (
                    "5413c6ffb4f8047977db9dba520453976f48eed91b5477d06e7f62258a2ba09c"
                ),
                "run_once": True,
                "retuning_authorized": False,
                "post_outcome_retry_authorized": False,
                "execution_id": "openvino-v7-test-execution",
                "authorization_nonce_sha256": "a" * 64,
            }
        )
        raw = (canonical_json(payload) + "\n").encode()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "auth.json"
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            verify_execution_authorization(path, digest, "PREPARE_REGISTRY")
            with self.assertRaises(RuntimeError):
                verify_execution_authorization(path, "0" * 64, "PREPARE_REGISTRY")
            with self.assertRaises(RuntimeError):
                verify_execution_authorization(path, digest, "MERGE")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = [
            {
                "row_index": 1,
                "image_id": "0000000000000001",
                "partition": 0,
                "selection_rank_sha256": h("r1"),
            },
            {
                "row_index": 2,
                "image_id": "0000000000000002",
                "partition": 1,
                "selection_rank_sha256": h("r2"),
            },
            {
                "row_index": 3,
                "image_id": "0000000000000003",
                "partition": 2,
                "selection_rank_sha256": h("r3"),
            },
            {
                "row_index": 4,
                "image_id": "0000000000000004",
                "partition": 3,
                "selection_rank_sha256": h("r4"),
            },
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
        registry = stable_payload(
            {
                **{
                    key: value
                    for key, value in registry.items()
                    if key != "stable_payload_sha256"
                },
                "authorization_binding": {
                    "execution_id": "synthetic-test",
                    "authorization_nonce_sha256": "b" * 64,
                    "authorization_stable_payload_sha256": "c" * 64,
                    "authorization_file_sha256": "d" * 64,
                },
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
    def make_reports(self, per_partition: int = 100) -> list[dict]:
        reports = []
        for partition in range(PARTITION_COUNT):
            rows = []
            for index in range(per_partition):
                observation.counter += 1
                rows.append(
                    observation(
                        partition=partition,
                        correct_baseline=(index % 4 != 0),
                        accepted=(index < per_partition // 2),
                        accepted_false=False,
                        counterfactual=False,
                    )
                )
            reports.append(
                stable_payload(
                    {
                        "schema": "eaat.openvino_v7_partition_report/1",
                        "partition_id": partition,
                        "partition_count": PARTITION_COUNT,
                        "record_count": len(rows),
                        "candidate_stable_payload_sha256": (
                            "160a3e79c6075a6741a1a6365b0c833115bfc6e156176cb4cb5744b1189119cd"
                        ),
                        "registry_stable_payload_sha256": h("registry"),
                        "scientific_manifest_sha256": (
                            "3340183dca08229e3cd1d17472043316867381d8b4f70e6f2d74e3592cd89d4c"
                        ),
                        "execution_complete": True,
                        "observations": rows,
                    }
                )
            )
        return reports

    def test_exact_summary_rejects_counterfactual_or_low_coverage(self):
        rows = []
        for index in range(1000):
            observation.counter += 1
            rows.append(
                observation(
                    partition=index % 12,
                    correct_baseline=(index % 10 != 0),
                    accepted=(index < 50),
                    counterfactual=(index == 0),
                )
            )
        summary = exact_summary(rows, minimum_selected=1)
        self.assertFalse(summary["pass"])
        self.assertLess(summary["coverage_lower"], 0.25)

    def test_aggregate_passes_complete_clean_reports_and_uses_leave_one_macrofold_out(
        self,
    ):
        reports = self.make_reports(500)
        result = aggregate_partition_reports(
            reports,
            expected_partition_counts=[500] * 12,
            registry_stable_payload_sha256=h("registry"),
            minimum_active=1,
        )
        self.assertEqual(result["status"], "PASS_FULL_EXTERNAL_GATE")
        self.assertEqual(result["stability"]["semantics"], "leave_one_macrofold_out")
        self.assertEqual(result["stability"]["passes"], 4)
        self.assertFalse(result["speed"]["claim_authorized"])

    def test_aggregate_rejects_missing_duplicate_or_nonterminal_partition(self):
        reports = self.make_reports(20)
        with self.assertRaises(RuntimeError):
            aggregate_partition_reports(
                reports[:-1],
                expected_partition_counts=[20] * 12,
                registry_stable_payload_sha256=h("registry"),
                minimum_active=1,
            )
        with self.assertRaises(RuntimeError):
            aggregate_partition_reports(
                reports + [copy.deepcopy(reports[0])],
                expected_partition_counts=[20] * 12,
                registry_stable_payload_sha256=h("registry"),
                minimum_active=1,
            )
        bad = copy.deepcopy(reports)
        bad[0]["execution_complete"] = False
        bad[0] = stable_payload(
            {
                key: value
                for key, value in bad[0].items()
                if key != "stable_payload_sha256"
            }
        )
        with self.assertRaises(RuntimeError):
            aggregate_partition_reports(
                bad,
                expected_partition_counts=[20] * 12,
                registry_stable_payload_sha256=h("registry"),
                minimum_active=1,
            )

    def test_aggregate_abstains_on_duplicate_physical_hash_or_quarantine_violation(
        self,
    ):
        reports = self.make_reports(20)
        reports[1]["observations"][0]["pixel_sha256"] = reports[0]["observations"][0][
            "pixel_sha256"
        ]
        reports[1] = stable_payload(
            {
                key: value
                for key, value in reports[1].items()
                if key != "stable_payload_sha256"
            }
        )
        result = aggregate_partition_reports(
            reports,
            expected_partition_counts=[20] * 12,
            registry_stable_payload_sha256=h("registry"),
            minimum_active=1,
        )
        self.assertEqual(result["status"], ABSTAIN_DEDUP_OR_INTEGRITY)
        reports = self.make_reports(20)
        reports[0]["observations"][0]["outcome_quarantine"][
            "detector_completed_before_annotation_query"
        ] = False
        reports[0] = stable_payload(
            {
                key: value
                for key, value in reports[0].items()
                if key != "stable_payload_sha256"
            }
        )
        result = aggregate_partition_reports(
            reports,
            expected_partition_counts=[20] * 12,
            registry_stable_payload_sha256=h("registry"),
            minimum_active=1,
        )
        self.assertEqual(result["status"], ABSTAIN_DEDUP_OR_INTEGRITY)


class ManifestBundleTests(unittest.TestCase):
    def test_partition_executor_persists_detector_barrier_before_annotations(self):
        from ocr_real_risk_v1 import openvino_full_gate_runner_v7 as module

        source = inspect.getsource(module.evaluate_partition_from_source)
        detector = source.index("_run_outcome_blind_detector")
        barrier_write = source.index("_write_jsonl(barrier_path")
        annotations = source.index("_fetch_partition_annotations")
        scoring = source.index("_score_partition_after_barrier")
        self.assertLess(detector, barrier_write)
        self.assertLess(barrier_write, annotations)
        self.assertLess(annotations, scoring)
        prepare_source = inspect.getsource(module.prepare_registry_from_source)
        self.assertNotIn("texts", prepare_source)
        self.assertNotIn("bboxes", prepare_source)
        self.assertNotIn("polygons", prepare_source)

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
