"""OpenVINO v7 metadata-only numeric power census.

The first stage reads only the transcription column and computes a deterministic
upper bound on selectable numeric image rows. Geometry is read only when that
upper bound can still satisfy the frozen power gate. The image column is never
selected, OCR and candidate inference are never executed, and no quality
outcome is observed in this workflow.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .core import canonical_json, sha256_bytes
from .textocr_adapter_v6 import (
    CENSUS_COLUMNS,
    EXPECTED_COLUMNS,
    canonical_numeric_text,
    census_rows,
)

DATASET_ID = "Yesianrohn/OCR-Data"
DATASET_REVISION = "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c"
COMPONENT = "openvino"
SOURCE_PATH = "data/openvino-00000-of-00001.parquet"
SOURCE_SHA256 = "5413c6ffb4f8047977db9dba520453976f48eed91b5477d06e7f62258a2ba09c"
SOURCE_SIZE_BYTES = 65_751_927_475
SOURCE_URL = (
    "https://huggingface.co/datasets/Yesianrohn/OCR-Data/resolve/"
    f"{DATASET_REVISION}/{SOURCE_PATH}?download=true"
)
ADAPTER_SCHEMA = "ocr-openvino-numeric-adapter/7"
CENSUS_SCHEMA = "ocr-openvino-numeric-census/7"
MINIMUM_SELECTED = 5000
MINIMUM_ACCEPTED = 400
DEVELOPMENT_ACCEPTANCE_NUMERATOR = 110
DEVELOPMENT_ACCEPTANCE_DENOMINATOR = 4674
DEVELOPMENT_ACCEPTANCE_RATE = (
    DEVELOPMENT_ACCEPTANCE_NUMERATOR / DEVELOPMENT_ACCEPTANCE_DENOMINATOR
)
REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS = math.ceil(
    MINIMUM_ACCEPTED / DEVELOPMENT_ACCEPTANCE_RATE
)


def stable_payload(
    payload: Mapping[str, Any], key: str = "stable_payload_sha256"
) -> dict[str, Any]:
    result = dict(payload)
    result.pop(key, None)
    result[key] = sha256_bytes(canonical_json(result).encode("utf-8"))
    return result


def _quote_sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sequence(value: object) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        raise RuntimeError("OpenVINO texts must be a sequence")
    return value


def texts_only_upper_bound(
    rows: Iterable[tuple[int, object]],
) -> dict[str, Any]:
    """Count rows that could survive the exact frozen geometry selection.

    This is an upper bound because invalid or conflicting geometry can only
    remove candidates in the exact stage; it cannot create a numeric candidate
    absent from the transcription list.
    """
    row_count = 0
    rows_with_candidate = 0
    numeric_annotations = 0
    seen_indices: set[int] = set()
    for row_index, texts in rows:
        if row_index in seen_indices:
            raise RuntimeError(f"duplicate OpenVINO row index: {row_index}")
        seen_indices.add(row_index)
        row_count += 1
        found = False
        for raw in _sequence(texts):
            if canonical_numeric_text(raw) is None:
                continue
            numeric_annotations += 1
            found = True
        if found:
            rows_with_candidate += 1
    projected = rows_with_candidate * DEVELOPMENT_ACCEPTANCE_RATE
    exact_stage_required = bool(
        rows_with_candidate >= MINIMUM_SELECTED
        and rows_with_candidate >= REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS
    )
    return {
        "row_count": row_count,
        "numeric_annotations_in_scope": numeric_annotations,
        "selected_upper_bound": rows_with_candidate,
        "projected_verified_upper_bound": projected,
        "minimum_selected": MINIMUM_SELECTED,
        "minimum_projected_verified": MINIMUM_ACCEPTED,
        "required_selected_for_projected_verified": (
            REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS
        ),
        "exact_geometry_stage_required": exact_stage_required,
    }


def exact_power_decision(selected: int) -> dict[str, Any]:
    projected = selected * DEVELOPMENT_ACCEPTANCE_RATE
    passed = bool(
        selected >= MINIMUM_SELECTED and projected >= MINIMUM_ACCEPTED
    )
    return {
        "minimum_selected": MINIMUM_SELECTED,
        "minimum_accepted": MINIMUM_ACCEPTED,
        "development_acceptance_rate": DEVELOPMENT_ACCEPTANCE_RATE,
        "development_acceptance_fraction": (
            f"{DEVELOPMENT_ACCEPTANCE_NUMERATOR}/"
            f"{DEVELOPMENT_ACCEPTANCE_DENOMINATOR}"
        ),
        "development_source": "opened TextOCR v6; no scientific credit",
        "required_selected_for_projected_accepted": (
            REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS
        ),
        "selected_available": selected,
        "selected_pass": selected >= MINIMUM_SELECTED,
        "projected_accepted": projected,
        "projected_accepted_pass": projected >= MINIMUM_ACCEPTED,
        "power_pass": passed,
    }


def remote_census(
    *,
    source_url: str,
    candidate_stable_payload_sha256: str,
    candidate_source_commit: str,
) -> dict[str, Any]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("duckdb is required for OpenVINO census") from exc
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
            f"OpenVINO Parquet is missing frozen columns: {missing}"
        )

    text_cursor = connection.execute(
        "SELECT file_row_number::BIGINT AS row_index, texts "
        f"FROM read_parquet({source}, file_row_number=true) "
        "ORDER BY file_row_number"
    )

    def text_rows() -> Iterable[tuple[int, object]]:
        scanned = 0
        while True:
            batch = text_cursor.fetchmany(512)
            if not batch:
                print(
                    json.dumps(
                        {
                            "stage": "texts_only_upper_bound",
                            "rows_scanned": scanned,
                            "status": "complete",
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                return
            scanned += len(batch)
            if scanned % 8192 == 0:
                print(
                    json.dumps(
                        {
                            "stage": "texts_only_upper_bound",
                            "rows_scanned": scanned,
                            "status": "in_progress",
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
            for row in batch:
                yield int(row[0]), row[1]

    stage_a = texts_only_upper_bound(text_rows())
    exact_census: dict[str, Any] | None = None
    geometry_columns_read = False
    if stage_a["exact_geometry_stage_required"]:
        geometry_columns_read = True
        exact_cursor = connection.execute(
            "SELECT file_row_number::BIGINT AS row_index, "
            "texts, bboxes, polygons, num_text_regions "
            f"FROM read_parquet({source}, file_row_number=true) "
            "ORDER BY file_row_number"
        )

        def exact_rows() -> Iterable[
            tuple[int, object, object, object, object]
        ]:
            scanned = 0
            while True:
                batch = exact_cursor.fetchmany(128)
                if not batch:
                    print(
                        json.dumps(
                            {
                                "stage": "exact_geometry_census",
                                "rows_scanned": scanned,
                                "status": "complete",
                            },
                            sort_keys=True,
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                    return
                scanned += len(batch)
                if scanned % 4096 == 0:
                    print(
                        json.dumps(
                            {
                                "stage": "exact_geometry_census",
                                "rows_scanned": scanned,
                                "status": "in_progress",
                            },
                            sort_keys=True,
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                for row in batch:
                    yield int(row[0]), row[1], row[2], row[3], row[4]

        exact_census = census_rows(exact_rows())
        selected = int(exact_census["selected_count"])
    else:
        selected = int(stage_a["selected_upper_bound"])

    power = exact_power_decision(selected)
    exact_complete = exact_census is not None
    power_is_conclusive = exact_complete or not bool(
        stage_a["exact_geometry_stage_required"]
    )
    if not power_is_conclusive:
        raise RuntimeError("OpenVINO power decision is not conclusive")
    if not exact_complete and power["power_pass"]:
        raise RuntimeError("upper-bound-only stage cannot authorize full gate")

    if exact_complete and power["power_pass"]:
        verdict = "OPENVINO_V7_SCHEMA_AND_POWER_GATE_PASS"
    elif exact_complete:
        verdict = "OPENVINO_V7_TERMINAL_EXACT_POWER_FAIL"
    else:
        verdict = "OPENVINO_V7_TERMINAL_UPPER_BOUND_POWER_FAIL"

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
            "stage_a_columns_only": ["texts"],
            "stage_b_columns_only": list(CENSUS_COLUMNS),
            "image_column_read": False,
            "geometry_columns_read": geometry_columns_read,
        },
        "selection": {
            "one_risk_unit_per_image_row": True,
            "uses_image_bytes": False,
            "uses_ocr": False,
            "uses_candidate_output": False,
            "stage_a_is_upper_bound_only": True,
            "stage_b_uses_byte_identical_textocr_v6_geometry_selection": True,
        },
        "stage_a_texts_only_upper_bound": stage_a,
        "exact_census": exact_census,
        "power_gate": {
            **power,
            "decision_basis": (
                "exact_geometry_census"
                if exact_complete
                else "texts_only_conservative_upper_bound"
            ),
            "decision_is_exact": exact_complete,
            "decision_is_conclusive": True,
            "metadata_power_pass": bool(
                exact_complete and power["power_pass"]
            ),
            "separate_full_gate_eligible_after_license_review": bool(
                exact_complete and power["power_pass"]
            ),
            "full_image_download_authorized": False,
            "ocr_authorized": False,
        },
        "decision": {
            "footer_and_metadata_columns_opened_after_candidate_freeze": True,
            "image_bytes_opened": False,
            "ocr_executed": False,
            "candidate_inference_executed": False,
            "external_certificate_claimed": False,
            "production_ready": False,
            "automatic_production_change": False,
            "license_review_required_before_full_image_download": True,
            "verdict": verdict,
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
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = dict(report)
    exact = summary.get("exact_census")
    if isinstance(exact, Mapping):
        exact = dict(exact)
        exact.pop("records", None)
        summary["exact_census"] = exact
    print(
        json.dumps(
            {
                "schema_fingerprint": summary["schema_fingerprint"],
                "stage_a_texts_only_upper_bound": summary[
                    "stage_a_texts_only_upper_bound"
                ],
                "exact_census": summary["exact_census"],
                "power_gate": summary["power_gate"],
                "decision": summary["decision"],
                "stable_payload_sha256": summary[
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
