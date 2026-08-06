"""COCO-Text v7 metadata-only numeric census.

The adapter reuses the already-audited TextOCR v6 geometry and deterministic
numeric-unit selection functions because the OCR-Data components share the
same Parquet schema. It changes only the immutable source binding, report
schema, and preregistered power gate. The image column is never selected.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .core import canonical_json, sha256_bytes
from .textocr_adapter_v6 import (
    CENSUS_COLUMNS,
    EXPECTED_COLUMNS,
    census_rows,
)

DATASET_ID = "Yesianrohn/OCR-Data"
DATASET_REVISION = "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c"
COMPONENT = "cocotext"
SOURCE_PATH = "data/cocotext-00000-of-00001.parquet"
SOURCE_SHA256 = "562176cbb803bb7aa140a4537701ef53ebb86e396c8927f9b160227ac49efd48"
SOURCE_SIZE_BYTES = 2_223_323_062
SOURCE_URL = (
    "https://huggingface.co/datasets/Yesianrohn/OCR-Data/resolve/"
    f"{DATASET_REVISION}/{SOURCE_PATH}?download=true"
)
ADAPTER_SCHEMA = "ocr-cocotext-numeric-adapter/7"
CENSUS_SCHEMA = "ocr-cocotext-numeric-census/7"
MINIMUM_SELECTED = 5000
MINIMUM_ACCEPTED = 400
DEVELOPMENT_ACCEPTANCE_RATE = 110 / 4674


def stable_payload(
    payload: Mapping[str, Any], key: str = "stable_payload_sha256"
) -> dict[str, Any]:
    result = dict(payload)
    result.pop(key, None)
    result[key] = sha256_bytes(canonical_json(result).encode("utf-8"))
    return result


def _quote_sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def remote_census(
    *,
    source_url: str,
    candidate_stable_payload_sha256: str,
    candidate_source_commit: str,
) -> dict[str, Any]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("duckdb is required for COCO-Text census") from exc
    if len(candidate_stable_payload_sha256) != 64:
        raise RuntimeError("candidate stable payload SHA-256 is invalid")
    if len(candidate_source_commit) != 40:
        raise RuntimeError("candidate source commit is invalid")

    connection = duckdb.connect(database=":memory:")
    connection.execute("SET threads=1")
    connection.execute("SET preserve_insertion_order=true")
    source = _quote_sql(source_url)
    description = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet({source})"
    ).fetchall()
    columns = [str(row[0]) for row in description]
    missing = [column for column in EXPECTED_COLUMNS if column not in columns]
    if missing:
        raise RuntimeError(
            f"COCO-Text Parquet is missing frozen columns: {missing}"
        )
    query = (
        "SELECT file_row_number::BIGINT AS row_index, "
        "texts, bboxes, polygons, num_text_regions "
        f"FROM read_parquet({source}, file_row_number=true) "
        "ORDER BY file_row_number"
    )
    cursor = connection.execute(query)

    def rows() -> Iterable[tuple[int, object, object, object, object]]:
        while True:
            batch = cursor.fetchmany(128)
            if not batch:
                return
            for row in batch:
                yield int(row[0]), row[1], row[2], row[3], row[4]

    census = census_rows(rows())
    selected = int(census["selected_count"])
    projected_accepted = selected * DEVELOPMENT_ACCEPTANCE_RATE
    power_pass = bool(
        selected >= MINIMUM_SELECTED
        and projected_accepted >= MINIMUM_ACCEPTED
    )
    report: dict[str, Any] = {
        "schema": CENSUS_SCHEMA,
        "adapter_schema": ADAPTER_SCHEMA,
        "dataset": {
            "id": DATASET_ID,
            "revision": DATASET_REVISION,
            "component": COMPONENT,
            "source_path": SOURCE_PATH,
            "source_sha256": SOURCE_SHA256,
            "source_size_bytes": SOURCE_SIZE_BYTES,
            "source_url": source_url,
        },
        "candidate_binding": {
            "stable_payload_sha256": candidate_stable_payload_sha256,
            "source_commit": candidate_source_commit,
        },
        "schema_fingerprint": {
            "columns": columns,
            "expected_columns": list(EXPECTED_COLUMNS),
            "census_columns_only": list(CENSUS_COLUMNS),
            "image_column_read": False,
        },
        "selection": {
            "one_risk_unit_per_image_row": True,
            "uses_image_bytes": False,
            "uses_ocr": False,
            "uses_candidate_output": False,
            "bbox_convention_resolved_against_polygon": True,
            "selection_implementation": (
                "byte-identical TextOCR v6 geometry/selection code"
            ),
        },
        "census": census,
        "power_gate": {
            "minimum_selected": MINIMUM_SELECTED,
            "minimum_accepted": MINIMUM_ACCEPTED,
            "development_acceptance_rate": DEVELOPMENT_ACCEPTANCE_RATE,
            "development_source": "opened TextOCR v6; no scientific credit",
            "selected_available": selected,
            "selected_pass": selected >= MINIMUM_SELECTED,
            "projected_accepted": projected_accepted,
            "projected_accepted_pass": (
                projected_accepted >= MINIMUM_ACCEPTED
            ),
            "download_full_source_and_run_ocr": power_pass,
        },
        "decision": {
            "footer_and_metadata_columns_opened_after_candidate_freeze": True,
            "image_bytes_opened": False,
            "ocr_executed": False,
            "candidate_inference_executed": False,
            "external_certificate_claimed": False,
            "production_ready": False,
            "automatic_production_change": False,
            "verdict": (
                "COCOTEXT_V7_SCHEMA_AND_POWER_GATE_PASS"
                if power_pass
                else "COCOTEXT_V7_TERMINAL_NO_FULL_DOWNLOAD"
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
    return stable_payload(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--candidate-stable", required=True)
    parser.add_argument("--candidate-source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = remote_census(
        source_url=args.source_url,
        candidate_stable_payload_sha256=args.candidate_stable,
        candidate_source_commit=args.candidate_source_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema_fingerprint": report["schema_fingerprint"],
                "census": {
                    key: value
                    for key, value in report["census"].items()
                    if key != "records"
                },
                "power_gate": report["power_gate"],
                "decision": report["decision"],
                "stable_payload_sha256": report[
                    "stable_payload_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
