from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ocr_real_risk_v1.openvino_full_gate_contract_v7 import (
    PRIOR_REGISTRY_SCHEMA,
    RETIRED_CORPORA,
    stable_payload,
)
from ocr_real_risk_v1.openvino_full_gate_registry_v7 import _load_prior_registry
from ocr_real_risk_v1.openvino_prior_registry_v7 import (
    EXPECTED_SOURCE_IDS,
    EXPECTED_TOTAL_ROWS,
    REGISTRY_STATUS,
)


def write_payload(path: Path, payload: dict) -> str:
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class PriorRegistryLoaderTests(unittest.TestCase):
    def test_self_hashed_but_empty_registry_is_rejected(self):
        weak = stable_payload(
            {
                "schema": PRIOR_REGISTRY_SCHEMA,
                "status": REGISTRY_STATUS,
                "complete": True,
                "scope": "FULL_PINNED_POPULATION_ALL_IMAGE_ROWS",
                "corpora": list(RETIRED_CORPORA),
                "source_ids": list(EXPECTED_SOURCE_IDS),
                "population_rows": EXPECTED_TOTAL_ROWS,
                "expected_population_rows": EXPECTED_TOTAL_ROWS,
                "unique_encoded_sha256": 0,
                "unique_pixel_sha256": 0,
                "encoded_sha256": [],
                "pixel_sha256": [],
                "source_receipts": [],
                "image_projection_only": True,
                "annotation_columns_read": False,
                "ocr_runs": 0,
                "candidate_inference_runs": 0,
                "openvino_scientific_images_opened": 0,
            }
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "prior_registry.json"
            digest = write_payload(path, weak)
            with self.assertRaises(RuntimeError):
                _load_prior_registry(path, digest)

    def test_wrong_population_or_source_set_is_rejected(self):
        for field, value in (
            ("population_rows", EXPECTED_TOTAL_ROWS - 1),
            ("source_ids", list(EXPECTED_SOURCE_IDS[:-1])),
            ("annotation_columns_read", True),
        ):
            payload = stable_payload(
                {
                    "schema": PRIOR_REGISTRY_SCHEMA,
                    "status": REGISTRY_STATUS,
                    "complete": True,
                    "scope": "FULL_PINNED_POPULATION_ALL_IMAGE_ROWS",
                    "corpora": list(RETIRED_CORPORA),
                    "source_ids": list(EXPECTED_SOURCE_IDS),
                    "population_rows": EXPECTED_TOTAL_ROWS,
                    "expected_population_rows": EXPECTED_TOTAL_ROWS,
                    "unique_encoded_sha256": 1,
                    "unique_pixel_sha256": 1,
                    "encoded_sha256": ["a" * 64],
                    "pixel_sha256": ["b" * 64],
                    "source_receipts": [],
                    "image_projection_only": True,
                    "annotation_columns_read": False,
                    "ocr_runs": 0,
                    "candidate_inference_runs": 0,
                    "openvino_scientific_images_opened": 0,
                }
            )
            payload = stable_payload(
                {
                    **{
                        key: item
                        for key, item in payload.items()
                        if key != "stable_payload_sha256"
                    },
                    field: value,
                }
            )
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "prior_registry.json"
                digest = write_payload(path, payload)
                with self.assertRaises(RuntimeError):
                    _load_prior_registry(path, digest)


if __name__ == "__main__":
    unittest.main()
