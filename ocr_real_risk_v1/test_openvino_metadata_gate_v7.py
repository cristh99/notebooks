from __future__ import annotations

import math
import unittest
from pathlib import Path

from . import openvino_adapter_v7
from .openvino_adapter_v7 import (
    DEVELOPMENT_ACCEPTANCE_RATE,
    REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS,
    exact_power_decision,
    stable_payload,
    texts_only_upper_bound,
)
from .openvino_source_seal_v7 import (
    RESOLVED_REVISION,
    SOURCE_PATH,
    SOURCE_SHA256,
    SOURCE_SIZE_BYTES,
    seal,
    verify,
)
from .openvino_terminal_v7 import adjudicate, verify_stable


class OpenVinoSourceSealV7Tests(unittest.TestCase):
    def test_exact_metadata_object_is_sealed_without_outcomes(self) -> None:
        metadata = {
            "sha": RESOLVED_REVISION,
            "siblings": [
                {
                    "rfilename": SOURCE_PATH,
                    "lfs": {
                        "size": SOURCE_SIZE_BYTES,
                        "sha256": SOURCE_SHA256,
                    },
                }
            ],
        }
        report = seal(metadata)
        self.assertTrue(verify(report))
        self.assertTrue(report["repository_metadata_only"])
        self.assertFalse(report["parquet_footer_read"])
        self.assertFalse(report["outcomes_opened"])
        self.assertEqual(report["images_opened"], 0)
        self.assertTrue(
            report["license_review"]["full_image_download_requires_review"]
        )

    def test_wrong_object_fails_closed(self) -> None:
        metadata = {
            "sha": RESOLVED_REVISION,
            "siblings": [
                {
                    "rfilename": SOURCE_PATH,
                    "lfs": {
                        "size": SOURCE_SIZE_BYTES,
                        "sha256": "0" * 64,
                    },
                }
            ],
        }
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            seal(metadata)


class OpenVinoMetadataGateV7Tests(unittest.TestCase):
    def test_texts_only_stage_is_a_conservative_row_upper_bound(self) -> None:
        report = texts_only_upper_bound(
            [
                (0, ["abc", "12-34"]),
                (1, ["2024"]),
                (2, ["1111"]),
                (3, ["987654", "5555"]),
                (4, ["no digits"]),
            ]
        )
        self.assertEqual(report["row_count"], 5)
        self.assertEqual(report["numeric_annotations_in_scope"], 2)
        self.assertEqual(report["selected_upper_bound"], 2)
        self.assertFalse(report["exact_geometry_stage_required"])

    def test_duplicate_row_index_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "duplicate OpenVINO"):
            texts_only_upper_bound([(1, ["1234"]), (1, ["5678"])])

    def test_power_boundary_is_exact_and_frozen(self) -> None:
        expected = math.ceil(400 / DEVELOPMENT_ACCEPTANCE_RATE)
        self.assertEqual(REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS, expected)
        self.assertFalse(
            exact_power_decision(expected - 1)["power_pass"]
        )
        at = exact_power_decision(expected)
        self.assertTrue(at["power_pass"])
        self.assertGreaterEqual(at["projected_accepted"], 400)

    def test_metadata_gate_never_authorizes_images_or_ocr_directly(self) -> None:
        self.assertTrue(callable(openvino_adapter_v7.remote_census))
        text = Path(openvino_adapter_v7.__file__).read_text()
        self.assertIn('"full_image_download_authorized": False', text)
        self.assertIn('"ocr_authorized": False', text)
        self.assertNotIn('"download_full_source_and_run_ocr"', text)

    def _terminal_inputs(self) -> tuple[dict, dict, dict, str]:
        source_commit = "a" * 40
        candidate = stable_payload(
            {
                "candidate_id": "numeric-consensus-v7-openvino",
                "source_commit": source_commit,
                "predecessor_v7": {
                    "stable_payload_sha256": (
                        "33d14875f0d2f9681ced662e452a5f28943ecb65e30a9242663d6a472034da9d"
                    )
                },
                "metadata_power_gate": {
                    "image_column_forbidden": True,
                    "full_image_download_authorized_in_this_gate": False,
                },
            }
        )
        source_seal = seal(
            {
                "sha": RESOLVED_REVISION,
                "siblings": [
                    {
                        "rfilename": SOURCE_PATH,
                        "lfs": {
                            "size": SOURCE_SIZE_BYTES,
                            "sha256": SOURCE_SHA256,
                        },
                    }
                ],
            }
        )
        stage_a = texts_only_upper_bound(
            [(0, ["12-34"]), (1, ["987654"]), (2, ["abc"])]
        )
        power = exact_power_decision(stage_a["selected_upper_bound"])
        report = stable_payload(
            {
                "schema": "ocr-openvino-numeric-census/7",
                "adapter_schema": "ocr-openvino-numeric-adapter/7",
                "dataset": {
                    "revision": RESOLVED_REVISION,
                    "source_path": SOURCE_PATH,
                    "source_sha256": SOURCE_SHA256,
                    "source_size_bytes": SOURCE_SIZE_BYTES,
                },
                "candidate_binding": {
                    "stable_payload_sha256": candidate[
                        "stable_payload_sha256"
                    ],
                    "source_commit": source_commit,
                },
                "schema_fingerprint": {
                    "image_column_read": False,
                    "stage_a_columns_only": ["texts"],
                    "stage_b_columns_only": [
                        "texts",
                        "bboxes",
                        "polygons",
                        "num_text_regions",
                    ],
                },
                "selection": {
                    "uses_image_bytes": False,
                    "uses_ocr": False,
                    "uses_candidate_output": False,
                },
                "stage_a_texts_only_upper_bound": stage_a,
                "exact_census": None,
                "power_gate": {
                    **power,
                    "decision_basis": (
                        "texts_only_conservative_upper_bound"
                    ),
                    "decision_is_exact": False,
                    "decision_is_conclusive": True,
                    "metadata_power_pass": False,
                    "separate_full_gate_eligible_after_license_review": False,
                    "full_image_download_authorized": False,
                    "ocr_authorized": False,
                },
                "decision": {
                    "image_bytes_opened": False,
                    "ocr_executed": False,
                    "candidate_inference_executed": False,
                    "license_review_required_before_full_image_download": True,
                    "verdict": (
                        "OPENVINO_V7_TERMINAL_UPPER_BOUND_POWER_FAIL"
                    ),
                },
                "constraints": {
                    "external_spend_usd": 0,
                    "gcloud_used": False,
                    "gpu_used": False,
                    "paid_api_used": False,
                    "production_modified": False,
                },
            }
        )
        return report, candidate, source_seal, source_commit

    def test_terminal_adjudicator_preserves_unknown_and_no_authorization(
        self,
    ) -> None:
        report, candidate, source_seal, source_commit = self._terminal_inputs()
        terminal = adjudicate(
            report,
            candidate,
            source_seal,
            source_commit=source_commit,
            census_file_sha256="b" * 64,
        )
        self.assertTrue(verify_stable(terminal))
        self.assertEqual(terminal["status"], "TERMINAL_UPPER_BOUND_POWER_FAIL")
        self.assertEqual(
            terminal["scientific_verdict"],
            "UNKNOWN_NO_IMAGE_OUTCOMES_OPENED",
        )
        self.assertFalse(terminal["full_image_download_authorized"])
        self.assertFalse(terminal["ocr_authorized"])

    def test_terminal_adjudicator_rejects_direct_image_authorization(
        self,
    ) -> None:
        report, candidate, source_seal, source_commit = self._terminal_inputs()
        unsafe = dict(report)
        unsafe.pop("stable_payload_sha256")
        unsafe["power_gate"] = dict(unsafe["power_gate"])
        unsafe["power_gate"]["full_image_download_authorized"] = True
        unsafe = stable_payload(unsafe)
        with self.assertRaisesRegex(RuntimeError, "power adjudication"):
            adjudicate(
                unsafe,
                candidate,
                source_seal,
                source_commit=source_commit,
                census_file_sha256="b" * 64,
            )

    def test_stable_payload_replays(self) -> None:
        first = stable_payload({"a": 1, "b": [2, 3]})
        second = stable_payload(first)
        self.assertEqual(first, second)
        self.assertEqual(len(first["stable_payload_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
