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

    def test_stable_payload_replays(self) -> None:
        first = stable_payload({"a": 1, "b": [2, 3]})
        second = stable_payload(first)
        self.assertEqual(first, second)
        self.assertEqual(len(first["stable_payload_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
